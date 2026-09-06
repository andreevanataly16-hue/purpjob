"""Выдать пользователю роль.

Отдельного эндпоинта «стать модератором» в продукте нет и быть не должно:
роль - это то, что назначает администратор, а не то, что запрашивает клиент.
Поэтому единственный способ её выдать - этот скрипт, запускаемый на сервере
человеком с доступом к базе.

    python -m scripts.set_role recruiter@example.com recruiter
"""

import sys

from app.access import ROLES
from app.db import SessionLocal
from app.models import User


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 1

    email, role = argv[0].strip().lower(), argv[1].strip()
    if role not in ROLES:
        print(f"Роль бывает только одна из: {', '.join(ROLES)}")
        return 1

    with SessionLocal() as db:
        user = db.query(User).filter_by(email=email).one_or_none()
        if user is None:
            print(f"Пользователь {email} не найден.")
            return 1

        previous = user.role
        user.role = role
        db.commit()

    print(f"{email}: {previous} -> {role}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
