"""Проверки модуля 16: готовность архитектуры к обратному подбору.

**Здесь нет реализации, и это правильный результат, а не недоделка.** Модуль 16
сам себя объявляет чертежом: «this document does not specify a buildable FRD»,
локальных наборов данных нет, приёмочных критериев нет, а §4 прямо запрещает
начинать инфраструктуру попутно с остальным. Строить агрегацию сейчас означало
бы предлагать рекрутеру отчёт «вот кто вам подходит» по базе, в которой ещё
нечего показывать, — та самая проблема, из-за которой модуль и помечен [V2].

Что здесь есть вместо кода: **контракт готовности**, записанный тестами. Модуль 16
обязан быть надстройкой, а не переписыванием, и единственный способ это
обеспечить — зафиксировать стыки так, чтобы их нельзя было незаметно сломать
между сегодняшним днём и тем днём, когда до модуля дойдут руки.

Главное разделение, ради которого всё это: PurpJob — инфраструктура доверия
(модули 1–15), а агрегация вакансий с обратным подбором — слой распространения
поверх. Если однажды окажется, что для обратного подбора нужно менять расчёт
Trust Score, значит, разделение нарушено, — и вот это проверяется первым.
"""

import inspect

from app import candidates as pool, requirements, trust as trust_logic, vacancies as library
from app.routers import recruiter as recruiter_router
from app.routers import retention as retention_router
from app.routers import trust as trust_router
from app.routers import vacancies as vacancies_router


# --- главное: расчёт доверия ничего не знает про вакансии -----------------


def test_trust_score_does_not_depend_on_vacancies_or_matching():
    """Модуль 16 обязан строиться как потребитель, а не как соавтор.

    Если обратный подбор однажды потребует правок в расчёте Trust Score - это
    признак нарушенного разделения, а не обычная деталь реализации. Проверяем
    отсутствие связи в ту сторону, пока её точно нет.
    """
    for module in (trust_logic, trust_router):
        source = inspect.getsource(module)
        assert "Vacancy" not in source
        assert "MatchResult" not in source
        assert "match_score" not in source


def test_match_never_writes_back_into_scoring():
    """Односторонняя связь: совпадение читает профиль и не трогает его."""
    for module in (library, vacancies_router, recruiter_router):
        source = inspect.getsource(module)
        assert "TrustScoreSnapshot" not in source
        assert "db.add(" not in source or module is recruiter_router


# --- §3, строка 1: происхождение вакансии и склейка дублей ---------------


def test_vacancy_keeps_every_source_it_came_from():
    """Настоящий агрегатор увидит одно объявление в нескольких каналах.

    Форма это уже держит: у вакансии список источников, а не одна строка, и
    склеенная карточка сохраняет их все.
    """
    multi = [item for item in library.ALL if len(item.source_channels) > 1]
    assert multi, "в наборе должна быть вакансия из нескольких каналов"
    assert all(item.source_channels for item in library.ALL)


# --- §3, строка 2: расчёт совпадения не знает, кто спросил ----------------


def test_match_engine_is_used_in_both_directions():
    """Кандидат→вакансия и вакансия→кандидаты - одна и та же функция.

    Обратный подбор - это тот же расчёт, запущенный по всей базе. Если бы
    сторона рекрутера считала своим способом, «тот же движок в другую сторону»
    было бы неправдой уже сейчас.
    """
    assert "library.compute(" in inspect.getsource(vacancies_router)
    assert "library.compute(" in inspect.getsource(recruiter_router)

    signature = inspect.signature(library.compute)
    assert list(signature.parameters) == ["vacancy", "state", "cluster_scores"]


def test_match_computation_has_no_notion_of_who_asked():
    """В расчёте нет ни кандидата, ни рекрутера - только профиль и вакансия."""
    source = inspect.getsource(library.compute)
    for forbidden in ("recruiter", "user", "session"):
        assert forbidden not in source.lower()


# --- §3, строка 3: у события «новая подходящая вакансия» есть дом ---------


def test_new_vacancy_event_has_a_shape_a_second_producer_can_fill():
    """Живой парсинг станет вторым производителем того же события.

    Сейчас производитель - локальная проверка по набору. Важно, что событие
    отделено от того, кто его породил: иначе настоящий конвейер пришлось бы
    вшивать внутрь модуля 11.
    """
    from app import growth

    assert growth.NEW_MATCHING_VACANCY in growth.TRIGGER_TYPES

    # Что считать «новым», решает отметка последней проверки, а не устройство
    # источника. Настоящий конвейер заменит именно её - и больше ничего.
    from app.models import VacancyCheckpoint

    assert "last_checked_at" in VacancyCheckpoint.__table__.columns

    signature = inspect.signature(retention_router.sweep)
    assert list(signature.parameters) == ["db", "user"]

    source = inspect.getsource(retention_router.sweep)
    for forbidden in ("http", "requests", "telegram", "parse_channel"):
        assert forbidden not in source.lower()


# --- §3, строка 4: приватность кандидата держится данными -----------------


def test_visibility_gate_is_structural_not_cosmetic():
    """Скрытый профиль не доходит до рекрутерской стороны вообще.

    Обратный подбор обязан звать этот же вход, а не заводить свою проверку
    видимости. Пока вход один - завести вторую легко не получится.
    """
    source = inspect.getsource(pool)
    assert "def visible_pool" in source

    recruiter_source = inspect.getsource(recruiter_router)
    # Рекрутерская сторона берёт кандидатов только через общий вход.
    assert "pool.visible_pool" in recruiter_source or "pool.pool_for" in recruiter_source
    assert "hidden" not in recruiter_source.split("def _candidate_or_404")[-1][:400]


def test_hidden_candidates_are_absent_from_the_pool():
    ids = {candidate.id for candidate in pool.visible_pool()}
    assert ids
    assert all(candidate.visibility_mode == "visible" for candidate in pool.visible_pool())


# --- §3, строка 5: показ кандидата рекрутеру - один путь ------------------


def test_recruiter_rendering_is_one_path():
    """Проактивный отчёт обратного подбора обязан идти через этот же показ.

    Второй, «свой» формат отчёта разошёлся бы с основным в первый же месяц -
    и рекрутер видел бы разные цифры на двух экранах одного продукта.
    """
    source = inspect.getsource(recruiter_router)
    assert source.count("def _detail(") == 1
    assert "CandidateDetailOut" in source


# --- §3, строка 6: разбор требований не зависит от источника текста -------


def test_requirement_extraction_is_independent_of_how_text_arrived():
    """Один разбор на набор модуля 10 и на вставленный текст модуля 15.

    Третий вызывающий - конвейер агрегации - встанет туда же без изменений.
    """
    signature = inspect.signature(requirements.extract)
    assert list(signature.parameters) == ["text"]

    source = inspect.getsource(requirements)
    for forbidden in ("request", "db", "Session", "user"):
        assert f"{forbidden}:" not in source.split("def extract")[1][:200]


# --- §4: попутно ничего не построено -------------------------------------


def test_no_aggregation_infrastructure_was_started():
    """§4 прямо запрещает начинать это попутно. Проверяем, что не начали.

    Соблазн «набросать хотя бы парсер» велик, а цена ошибки - месяцы работы
    над слоем, который бессмысленно включать, пока проверенных профилей мало.
    """
    from pathlib import Path

    backend = Path(__file__).resolve().parents[1] / "app"
    sources = "\n".join(
        path.read_text(encoding="utf-8") for path in backend.rglob("*.py")
    ).lower()

    for forbidden in ("telethon", "scrapy", "beautifulsoup", "vector_db", "celery", "apscheduler"):
        assert forbidden not in sources, forbidden


def test_junk_filter_is_honestly_absent():
    """Фильтр В - единственный настоящий пробел, а не «где-то уже есть».

    Он понадобится, когда лента станет большой; сейчас её качество держится на
    том, что набор собран руками. Называть это реализованным было бы неправдой.
    """
    source = inspect.getsource(library)
    assert "filter_v" not in source.lower()
    assert "junk" not in source.lower()
