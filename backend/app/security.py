"""Хеширование паролей и токены сессий.

Пароли хешируются scrypt из стандартной библиотеки: это признанная функция
для паролей (RFC 7914), стойкая к перебору на видеокартах, и она не тянет
внешних зависимостей. Формат хранения: scrypt$n$r$p$<соль>$<хеш>, параметры
лежат внутри строки — если завтра мы их поднимем, старые хеши продолжат
проверяться своими.
"""

import hashlib
import secrets

# Параметры scrypt. n=2**14 при r=8 — примерно 16 МБ памяти на проверку.
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SALT_BYTES = 16
KEY_BYTES = 32


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(SALT_BYTES)
    key = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=KEY_BYTES,
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${key.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, n, r, p, salt_hex, key_hex = stored.split("$")
        if algorithm != "scrypt":
            return False
        key = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(bytes.fromhex(key_hex)),
        )
    except (ValueError, TypeError):
        # Битая или чужая строка хеша - это не совпадение, а не исключение.
        return False

    # Сравнение за постоянное время, чтобы по времени ответа нельзя было
    # подбирать хеш побайтово.
    return secrets.compare_digest(key.hex(), key_hex)


def new_session_token() -> str:
    """Непрозрачный токен сессии. Уходит клиенту, в базе не хранится."""
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    """То, что кладётся в базу вместо токена.

    Здесь достаточно обычного SHA-256, без scrypt: токен - это 256 бит
    случайности, перебирать его бессмысленно, замедлять проверку незачем.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
