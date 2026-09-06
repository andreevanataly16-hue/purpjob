"""Ограничение попыток входа.

Зачем. До этого модуля пароль можно было перебирать бесконечно: форма входа
принимала сколько угодно попыток подряд. Для приложения, доступного из
интернета, это блокер даже для маленького закрытого пилота - подбор пароля не
требует ни умения, ни оборудования.

Чем это НЕ является. Это не распределённый production-limiter. Счётчики живут
в памяти процесса: при перезапуске они обнуляются, а при нескольких рабочих
процессах у каждого свой счёт. Для пилота на одном процессе этого достаточно и
это осознанный выбор - тянуть Redis ради одного счётчика в закрытый пилот
дороже, чем польза. Граница описана в README, чтобы её не приняли за готовое
production-решение.

Два ведра, а не одно:

* **счёт + адрес** - защищает конкретную учётную запись от подбора пароля;
* **адрес** - защищает от размазывания попыток по многим учётным записям,
  когда по каждой в отдельности лимит не достигается.

Считаются только неудачи. Успешный вход обнуляет ведро: человек, который
вспомнил свой пароль с четвёртого раза, ничего не должен продукту.

Ответ не зависит от того, существует ли учётная запись. Ведро заводится по
присланному адресу, а не по найденному пользователю, и до проверки пароля
никто не знает, есть ли такой человек вообще - иначе форма входа стала бы
способом узнать, кто здесь зарегистрирован, только другим путём.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field

# Отдельный вход - штука редкая: человек вводит пароль один раз в месяц, а не
# двадцать раз в минуту. Пятнадцать неудач подряд по одной учётной записи -
# это уже не опечатки. Цифры осознанно щедрые: заблокировать настоящего
# кандидата хуже, чем пропустить лишнюю попытку перебора.
DEFAULT_MAX_ATTEMPTS = 15
DEFAULT_WINDOW_SECONDS = 300

# По адресу лимит выше: за одним IP может сидеть офис или мобильный оператор,
# и один забывчивый человек не должен закрывать вход всем остальным.
DEFAULT_ADDRESS_MAX_ATTEMPTS = 60

TOO_MANY_ATTEMPTS_RU = (
    "Слишком много попыток входа. Подождите несколько минут и попробуйте снова."
)


@dataclass
class _Bucket:
    """Отметки времени неудач. Очередь, а не счётчик: окно скользящее."""

    hits: deque[float] = field(default_factory=deque)


class LoginRateLimiter:
    """Скользящее окно по двум ключам.

    Часы передаются снаружи, чтобы тест на «после окна лимит сбрасывается» не
    ждал пять минут по-настоящему. Ждать в тесте - значит либо сделать его
    медленным, либо уменьшить окно и проверять не то, что работает в проде.
    """

    def __init__(
        self,
        *,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        address_max_attempts: int = DEFAULT_ADDRESS_MAX_ATTEMPTS,
        window_seconds: int = DEFAULT_WINDOW_SECONDS,
        clock=time.monotonic,
    ) -> None:
        self.max_attempts = max_attempts
        self.address_max_attempts = address_max_attempts
        self.window_seconds = window_seconds
        self.clock = clock
        self._buckets: dict[tuple[str, str], _Bucket] = {}
        # Uvicorn держит синхронные обработчики в пуле потоков, поэтому словарь
        # правится под замком: без него две одновременные попытки могут
        # потерять одну отметку и лимит окажется мягче обещанного.
        self._lock = threading.Lock()

    # --- ключи ------------------------------------------------------------

    @staticmethod
    def account_key(address: str, identifier: str) -> tuple[str, str]:
        """Адрес почты приводится к одному виду: Nataly@ и nataly@ - один счёт."""
        return ("account", f"{address}|{identifier.strip().lower()}")

    @staticmethod
    def address_key(address: str) -> tuple[str, str]:
        return ("address", address)

    # --- проверка и учёт --------------------------------------------------

    def _fresh(self, bucket: _Bucket, now: float) -> deque[float]:
        horizon = now - self.window_seconds
        while bucket.hits and bucket.hits[0] <= horizon:
            bucket.hits.popleft()
        return bucket.hits

    def _limit_for(self, key: tuple[str, str]) -> int:
        return self.max_attempts if key[0] == "account" else self.address_max_attempts

    def retry_after(self, address: str, identifier: str) -> int | None:
        """Сколько секунд ждать. None - лимит не достигнут, можно пробовать.

        Проверка не считается попыткой: попытку записывает только `register_failure`.
        """
        now = self.clock()
        with self._lock:
            wait = 0
            for key in (self.account_key(address, identifier), self.address_key(address)):
                bucket = self._buckets.get(key)
                if bucket is None:
                    continue
                hits = self._fresh(bucket, now)
                if len(hits) >= self._limit_for(key):
                    wait = max(wait, int(self.window_seconds - (now - hits[0])) + 1)
            return wait or None

    def register_failure(self, address: str, identifier: str) -> None:
        now = self.clock()
        with self._lock:
            for key in (self.account_key(address, identifier), self.address_key(address)):
                bucket = self._buckets.setdefault(key, _Bucket())
                self._fresh(bucket, now)
                bucket.hits.append(now)

    def register_success(self, address: str, identifier: str) -> None:
        """Удачный вход снимает счёт с учётной записи.

        Ведро по адресу остаётся: один угаданный пароль не должен обнулять
        след от перебора по остальным учётным записям с того же адреса.
        """
        with self._lock:
            self._buckets.pop(self.account_key(address, identifier), None)

    def reset(self) -> None:
        """Для тестов: между ними счётчики не должны протекать."""
        with self._lock:
            self._buckets.clear()


# Один на процесс. Границы этого решения описаны в docstring модуля.
login_limiter = LoginRateLimiter()


def client_address(request) -> str:
    """Адрес обращающегося.

    За обратным прокси реальный адрес приходит в заголовке, но доверять
    заголовку, который присылает сам клиент, нельзя: тогда лимит обходится
    одной строкой. Пока пилот работает без доверенного прокси, берётся адрес
    соединения; появится прокси - здесь появится его разбор, и только его.
    """
    return request.client.host if request.client else "неизвестно"
