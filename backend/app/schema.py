"""Проверка, что схема базы соответствует коду.

До появления миграций схема создавалась вызовом `create_all()`. Он умеет
только одно - создать недостающие таблицы. Добавить столбец в уже
существующую он не может и об этом не сообщает: приложение поднималось
нормально, а падало потом, на первом запросе, который этот столбец читал.
Именно так это и проявилось на модуле 11.

Здесь только проверка. Применять миграции на старте приложения нельзя:
изменение схемы рабочей базы не должно случаться побочным эффектом запуска.
Команду выполняет человек - или пусковой скрипт перед запуском сервера.
"""

from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = BACKEND_ROOT / "alembic.ini"

OUTDATED_RU = """
База данных не соответствует коду.

  в базе:  {current}
  нужно:   {head}

Примените миграции - из папки backend:

    python -m alembic upgrade head

Если база создавалась до появления миграций (в ней уже есть все таблицы, но
нет ролей и журнала обращений), сначала отметьте базовую ревизию:

    python -m alembic stamp {baseline}
    python -m alembic upgrade head
"""


class SchemaOutdated(RuntimeError):
    """Схема базы отстала от кода. Сообщение содержит команду для починки."""


def _script() -> ScriptDirectory:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return ScriptDirectory.from_config(config)


def current_revision(engine: Engine) -> str | None:
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def assert_schema_current(engine: Engine) -> None:
    """Падает с внятным сообщением, если миграции не применены.

    Падать на старте здесь правильнее, чем работать на несовпадающей схеме:
    вторая ошибка приходит позже, в середине работы кандидата, и выглядит как
    что угодно, кроме своей настоящей причины.
    """
    script = _script()
    head = script.get_current_head()
    current = current_revision(engine)

    if current == head:
        return

    baseline = next(
        (revision.revision for revision in script.walk_revisions() if revision.down_revision is None),
        "<baseline>",
    )
    raise SchemaOutdated(
        OUTDATED_RU.format(
            current=current or "миграции никогда не применялись",
            head=head,
            baseline=baseline,
        )
    )
