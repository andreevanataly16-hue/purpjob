"""Роли и журнал обращений (стабилизационный спринт).

До этой ревизии роли не было вообще: любой вошедший мог открыть очередь
модератора и посмотреть базу кандидатов. Роль хранится у пользователя и только
там - присланную клиентом не читает никто.

Журнал обращений содержит кто, что, над кем и когда. Содержимого в нём нет
намеренно: он не должен становиться вторым местом, где лежит закрытое под NDA.

Revision ID: 76201fb
Revises: 76201fab2384
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "76201fb"
down_revision: Union[str, Sequence[str], None] = "76201fab2384"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Добавляет роль и журнал обращений.

    Обе операции защищены проверкой существования, и это не перестраховка.
    До появления миграций схему создавал `create_all()`: в базе, которая
    поднималась после того, как модель журнала уже была написана, таблица
    журнала есть - а столбца роли нет, потому что добавлять столбцы в
    существующие таблицы `create_all()` не умеет.

    Такое полуприменённое состояние - разовое следствие эпохи без миграций.
    Дальше ревизии пишутся обычным способом: этот приём нужен ровно здесь, на
    границе перехода.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    columns = {column["name"] for column in inspector.get_columns("users")}
    if "role" not in columns:
        # Значение по умолчанию нужно и на уровне базы: у существующих строк
        # роли нет, а роль обязана быть у всех - и самая безобидная из трёх.
        with op.batch_alter_table("users", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "role",
                    sa.String(length=20),
                    nullable=False,
                    server_default="candidate",
                )
            )

    if "access_log" not in inspector.get_table_names():
        op.create_table(
            "access_log",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("actor_user_id", sa.Integer(), nullable=False),
            sa.Column("actor_role", sa.String(length=20), nullable=False),
            sa.Column("action", sa.String(length=200), nullable=False),
            sa.Column("target", sa.String(length=120), nullable=False),
            sa.Column("note", sa.String(length=200), nullable=True),
            sa.Column(
                "at",
                sa.DateTime(timezone=True),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("access_log", schema=None) as batch_op:
            batch_op.create_index(
                batch_op.f("ix_access_log_actor_user_id"), ["actor_user_id"], unique=False
            )


def downgrade() -> None:
    with op.batch_alter_table("access_log", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_access_log_actor_user_id"))
    op.drop_table("access_log")

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("role")
