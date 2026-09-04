"""Эталонная таксономия компетенций первого сегмента.

Сегмент зафиксирован роадмапом: Backend/Fullstack, Python/Go, Middle/Senior.

Ключ `key` - канонический английский идентификатор: по нему компетенция позже
сопоставится с эталонной библиотекой PROF (модуль 3). Кандидату показывается
`ru`. Категории - из §3.1 FRD, менять их состав нельзя: на них опирается
Evidence Map.

`patterns` - регулярные выражения по тексту кандидата. Русский язык склоняется,
поэтому большинство образцов - основы слов ("нагрузк" ловит "нагрузку",
"нагрузками"), а не целые слова.
"""

import re

HARD_SKILL = "Hard Skill"
PRACTICAL = "Practical Understanding"
FOOTPRINT = "Professional Footprint"
COMPLEXITY = "Complexity of Solved Tasks"

CATEGORIES = (HARD_SKILL, PRACTICAL, FOOTPRINT, COMPLEXITY)

# (канонический ключ, название для кандидата, категория, образцы)
_RAW_TAXONOMY: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("Python", "Python", HARD_SKILL, (r"python", r"питон")),
    ("Go", "Go", HARD_SKILL, (r"\bgo(lang)?\b", r"голанг")),
    ("REST API design", "Проектирование REST API", HARD_SKILL, (r"rest[ -]?api", r"\brest\b", r"\bapi\b", r"эндпоинт")),
    ("gRPC", "gRPC", HARD_SKILL, (r"grpc",)),
    ("PostgreSQL", "PostgreSQL", HARD_SKILL, (r"postgres", r"постгрес", r"psql")),
    ("Database design", "Проектирование баз данных", HARD_SKILL, (r"баз[аыуе]?\w* данных", r"\bбд\b", r"схем[уаы]\w* баз", r"индекс", r"миграци", r"нормализ")),
    ("Query optimization", "Оптимизация запросов", HARD_SKILL, (r"оптимизир\w*\s+запрос", r"медленн\w*\s+запрос", r"n\+1", r"explain analyze", r"slow quer")),
    ("Caching", "Кеширование", HARD_SKILL, (r"redis", r"редис", r"\bкеш", r"\bкэш", r"memcache")),
    ("Message queues", "Очереди сообщений", HARD_SKILL, (r"kafka", r"кафк", r"rabbitmq", r"очеред\w*\s+сообщен", r"брокер")),
    ("Docker", "Docker", HARD_SKILL, (r"docker", r"докер", r"контейнериз")),
    ("Kubernetes", "Kubernetes", HARD_SKILL, (r"kubernetes", r"k8s", r"кубер")),
    ("CI/CD", "CI/CD", HARD_SKILL, (r"ci/cd", r"github actions", r"gitlab ci", r"jenkins", r"дженкинс", r"деплой\w*\s+пайплайн")),
    ("Asynchronous programming", "Асинхронное программирование", HARD_SKILL, (r"asyncio", r"async", r"асинхрон", r"корутин", r"goroutine", r"горутин")),
    ("Testing", "Тестирование", HARD_SKILL, (r"\bтест", r"pytest", r"unit[- ]test", r"покрыти\w*\s+код", r"мок\w*\b")),
    ("Observability", "Мониторинг и наблюдаемость", HARD_SKILL, (r"prometheus", r"grafana", r"мониторинг", r"метрик", r"логирован", r"трейсинг", r"sentry", r"jaeger")),
    ("Cloud infrastructure", "Облачная инфраструктура", HARD_SKILL, (r"\baws\b", r"\bgcp\b", r"terraform", r"\bs3\b", r"облак")),
    ("Frontend", "Фронтенд", HARD_SKILL, (r"react", r"\bvue\b", r"typescript", r"javascript", r"фронтенд")),
    ("Security", "Безопасность", HARD_SKILL, (r"безопасност", r"oauth", r"\bjwt\b", r"шифров", r"уязвимост", r"аутентификац", r"авторизац")),
    ("Data pipelines", "Обработка данных", HARD_SKILL, (r"\betl\b", r"airflow", r"пайплайн\w*\s+данных", r"витрин")),

    ("Architecture decisions", "Архитектурные решения", PRACTICAL, (r"архитектур", r"trade-?off", r"компромисс", r"выбор между", r"почему выбра", r"решили использовать", r"проектирова")),
    ("Code review and mentoring", "Ревью и наставничество", PRACTICAL, (r"код-?ревью", r"code review", r"\bревью", r"менторств", r"наставнич", r"стажёр", r"стажер", r"обучал")),
    ("Incident response", "Работа с инцидентами", PRACTICAL, (r"инцидент", r"авари", r"постмортем", r"postmortem", r"дежурств", r"on-?call", r"упал\w*\s+прод")),
    ("Refactoring legacy", "Работа с легаси", PRACTICAL, (r"рефакторинг", r"легаси", r"legacy", r"техдолг", r"техническ\w*\s+долг")),
    ("Product and requirements", "Работа с требованиями", PRACTICAL, (r"требовани", r"продакт", r"бизнес-задач", r"заказчик", r"стейкхолдер")),

    ("High load systems", "Высокие нагрузки", COMPLEXITY, (r"highload", r"высок\w*\s+нагрузк", r"нагрузк", r"\brps\b", r"тысяч\w*\s+запрос", r"миллион")),
    ("Distributed systems", "Распределённые системы", COMPLEXITY, (r"распределённ", r"распределенн", r"микросервис", r"шардир", r"репликац", r"консистентност")),
    ("System from scratch", "Система с нуля", COMPLEXITY, (r"с нуля", r"greenfield", r"с чистого листа", r"перв\w*\s+релиз", r"запустил\w*\s+сервис")),
    ("Large scale migration", "Миграция систем", COMPLEXITY, (r"миграци\w*\s+данн", r"переезд", r"перенос\w*\s+систем", r"переписал", r"переход\w*\s+с\b")),
    ("Performance optimization", "Оптимизация производительности", COMPLEXITY, (r"ускорил", r"оптимизир", r"производительност", r"latency", r"задержк", r"\bp99\b")),

    ("Public speaking", "Публичные выступления", FOOTPRINT, (r"доклад", r"конференц", r"митап", r"meetup", r"выступа")),
    ("Technical writing", "Технические тексты", FOOTPRINT, (r"стать[юия]", r"\bблог", r"хабр", r"туториал", r"написал\w*\s+документаци")),
    ("Open source", "Open source", FOOTPRINT, (r"open ?source", r"опенсорс", r"контрибь", r"pull request", r"библиотек\w*\s+в открыт")),
)


class Competency:
    """Одна компетенция таксономии с уже скомпилированными образцами."""

    __slots__ = ("key", "ru", "category", "regexes")

    def __init__(self, key: str, ru: str, category: str, patterns: tuple[str, ...]) -> None:
        self.key = key
        self.ru = ru
        self.category = category
        self.regexes = [re.compile(p, re.IGNORECASE) for p in patterns]


TAXONOMY: tuple[Competency, ...] = tuple(
    Competency(key, ru, category, patterns) for key, ru, category, patterns in _RAW_TAXONOMY
)

BY_KEY: dict[str, Competency] = {c.key: c for c in TAXONOMY}
