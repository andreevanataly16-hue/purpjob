"""Ограничение попыток входа (подготовка к Candidate Pilot).

До этого модуля пароль можно было перебирать бесконечно. Здесь проверяется не
«лимит существует», а что он ведёт себя так, как обещано человеку: обычные
опечатки проходят, перебор упирается в стену, стена сама исчезает через окно,
и по ответу нельзя понять, есть ли такая почта.
"""

import pytest

from app.ratelimit import (
    DEFAULT_MAX_ATTEMPTS,
    TOO_MANY_ATTEMPTS_RU,
    LoginRateLimiter,
    login_limiter,
)

REGISTER = "/api/auth/register"
LOGIN = "/api/auth/login"

EMAIL = "nataly@example.com"
PASSWORD = "verysecret123"
WRONG = "verysecret124"


class Clock:
    """Часы, которые двигает тест.

    Иначе проверка «через пять минут снова можно» либо занимала бы пять минут,
    либо потребовала бы уменьшить окно - то есть проверяла бы не ту настройку,
    с которой продукт работает.
    """

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def forward(self, seconds):
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    fake = Clock()
    monkeypatch.setattr(login_limiter, "clock", fake)
    return fake


def bad_login(client, email=EMAIL):
    return client.post(LOGIN, json={"email": email, "password": WRONG})


# --- обычная жизнь --------------------------------------------------------


def test_a_few_mistakes_are_just_mistakes(client, credentials, clock):
    """Человек, промахнувшийся мимо пароля, не должен упереться в стену."""
    client.post(REGISTER, json=credentials)

    for _ in range(DEFAULT_MAX_ATTEMPTS - 1):
        assert bad_login(client).status_code == 401


def test_the_right_password_still_works_after_mistakes(client, credentials, clock):
    client.post(REGISTER, json=credentials)
    for _ in range(DEFAULT_MAX_ATTEMPTS - 1):
        bad_login(client)

    assert client.post(LOGIN, json=credentials).status_code == 200


def test_a_successful_login_clears_the_count(client, credentials, clock):
    """Вспомнил пароль - счёт обнулился. Иначе лимит копился бы месяцами."""
    client.post(REGISTER, json=credentials)
    for _ in range(DEFAULT_MAX_ATTEMPTS - 1):
        bad_login(client)
    client.post(LOGIN, json=credentials)

    # Снова полный запас попыток, а не одна оставшаяся.
    for _ in range(DEFAULT_MAX_ATTEMPTS - 1):
        assert bad_login(client).status_code == 401


# --- стена ----------------------------------------------------------------


def test_the_limit_answers_429(client, credentials, clock):
    client.post(REGISTER, json=credentials)
    for _ in range(DEFAULT_MAX_ATTEMPTS):
        bad_login(client)

    response = bad_login(client)
    assert response.status_code == 429
    assert response.json()["detail"] == TOO_MANY_ATTEMPTS_RU
    # Человеку говорят, сколько ждать, а не оставляют гадать.
    assert int(response.headers["Retry-After"]) > 0


def test_the_right_password_is_refused_while_the_limit_holds(client, credentials, clock):
    """Иначе лимит обходится тем, что перебор идёт до первой удачи."""
    client.post(REGISTER, json=credentials)
    for _ in range(DEFAULT_MAX_ATTEMPTS):
        bad_login(client)

    assert client.post(LOGIN, json=credentials).status_code == 429


def test_the_limit_lifts_itself_after_the_window(client, credentials, clock):
    """Блокировка временная. Постоянная превратилась бы в способ закрыть
    человеку вход, зная только его почту."""
    client.post(REGISTER, json=credentials)
    for _ in range(DEFAULT_MAX_ATTEMPTS):
        bad_login(client)
    assert bad_login(client).status_code == 429

    clock.forward(login_limiter.window_seconds + 1)

    assert client.post(LOGIN, json=credentials).status_code == 200


# --- разделение вёдер -----------------------------------------------------


def test_one_blocked_account_does_not_block_another(client, credentials, clock):
    """Перебор по одной почте не должен закрывать вход соседу.

    Ведро по адресу здесь ещё далеко от своего лимита - оно рассчитано ровно
    на этот случай: несколько человек за одним IP.
    """
    client.post(REGISTER, json=credentials)
    client.post(REGISTER, json={"email": "someone@example.com", "password": PASSWORD})

    for _ in range(DEFAULT_MAX_ATTEMPTS):
        bad_login(client)
    assert bad_login(client).status_code == 429

    assert client.post(
        LOGIN, json={"email": "someone@example.com", "password": PASSWORD}
    ).status_code == 200


def test_the_account_bucket_ignores_letter_case(client, credentials, clock):
    """Иначе лимит обходится заглавной буквой в почте."""
    client.post(REGISTER, json=credentials)
    for _ in range(DEFAULT_MAX_ATTEMPTS):
        bad_login(client)

    assert bad_login(client, email="Nataly@Example.com").status_code == 429


def test_spraying_across_accounts_runs_into_the_address_bucket():
    """Второе ведро: попытки размазаны по многим почтам, лимит по учётной
    записи не достигается ни разу, а перебор всё равно должен упереться."""
    limiter = LoginRateLimiter(max_attempts=3, address_max_attempts=5, window_seconds=60)

    for index in range(5):
        assert limiter.retry_after("10.0.0.1", f"user{index}@example.com") is None
        limiter.register_failure("10.0.0.1", f"user{index}@example.com")

    assert limiter.retry_after("10.0.0.1", "user99@example.com") is not None
    # Другой адрес не задет.
    assert limiter.retry_after("10.0.0.2", "user99@example.com") is None


# --- существование учётной записи -----------------------------------------


def test_an_unknown_email_is_answered_exactly_like_a_known_one(client, credentials, clock):
    """Ни код, ни текст, ни момент включения лимита не должны различаться.

    Иначе форма входа становится способом проверить, зарегистрирован ли
    человек: достаточно посмотреть, где кончается терпение сервера.
    """
    client.post(REGISTER, json=credentials)

    known = [bad_login(client) for _ in range(DEFAULT_MAX_ATTEMPTS + 1)]
    login_limiter.reset()
    unknown = [
        bad_login(client, email="nobody@example.com")
        for _ in range(DEFAULT_MAX_ATTEMPTS + 1)
    ]

    assert [r.status_code for r in known] == [r.status_code for r in unknown]
    assert [r.json()["detail"] for r in known] == [r.json()["detail"] for r in unknown]


def test_the_limit_message_says_nothing_about_the_account():
    assert "почт" not in TOO_MANY_ATTEMPTS_RU.lower()
    assert "парол" not in TOO_MANY_ATTEMPTS_RU.lower()


# --- что лимит не должен делать -------------------------------------------


def test_no_password_is_written_anywhere_by_the_limiter():
    """Ведро хранит время и ключ - и ни одного присланного пароля."""
    limiter = LoginRateLimiter()
    limiter.register_failure("10.0.0.1", "nataly@example.com")

    stored = repr(limiter.__dict__)
    assert PASSWORD not in stored
    assert WRONG not in stored


def test_checking_the_limit_is_not_itself_an_attempt():
    """Иначе опрос состояния сам бы и приводил к блокировке."""
    limiter = LoginRateLimiter(max_attempts=2, window_seconds=60)

    for _ in range(10):
        assert limiter.retry_after("10.0.0.1", "nataly@example.com") is None
