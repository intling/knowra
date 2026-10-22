import re

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.errors import AppError

_hasher = PasswordHasher()
# Unknown accounts perform the same password verification work as known accounts.
DUMMY_HASH = _hasher.hash("knowra-dummy-password-2026")


def normalize_email(value: str) -> str:
    email = value.strip().lower()
    if len(email) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise AppError(422, "invalid_email", "请输入有效邮箱（最多 254 个字符）")
    return email


def normalize_display_name(value: str) -> str:
    name = value.strip()
    if not 1 <= len(name) <= 100:
        raise AppError(422, "invalid_display_name", "显示名须为 1–100 个字符")
    return name


def validate_password(password: str, *, email: str) -> None:
    if not 10 <= len(password) <= 128:
        raise AppError(422, "weak_password", "密码长度须为 10–128 个字符")
    if not any(char.isalpha() for char in password) or not any(char.isdigit() for char in password):
        raise AppError(422, "weak_password", "密码须同时包含字母和数字")
    if password.lower() in (email.lower(), email.split("@")[0].lower()):
        raise AppError(422, "weak_password", "密码不能与邮箱或邮箱用户名相同")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(hashed: str, password: str) -> bool:
    try:
        return _hasher.verify(hashed, password)
    except VerificationError, InvalidHashError:
        return False


def needs_rehash(hashed: str) -> bool:
    return _hasher.check_needs_rehash(hashed)
