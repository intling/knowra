# 用户体系红测试：密码策略、输入规范化、argon2id 哈希、角色权限矩阵与登录限流器。
# 这些是纯函数/内存对象，不依赖数据库，覆盖规则边界与失败分支。

import pytest
from argon2 import PasswordHasher

from app.core.errors import AppError
from app.core.permissions import permissions_for
from app.services import passwords
from app.services.auth import LoginRateLimiter
from app.services.passwords import (
    hash_password,
    needs_rehash,
    normalize_display_name,
    normalize_email,
    validate_password,
    verify_password,
)


def assert_app_error(exc_info: pytest.ExceptionInfo[AppError], *, status: int, code: str) -> None:
    error = exc_info.value
    assert error.status_code == status, (
        f"期望 HTTP {status}，实际 {error.status_code}；detail={error.detail}"
    )
    assert error.code == code, f"期望错误码 {code}，实际 {error.code}；detail={error.detail}"
    assert error.detail, "错误必须附带可读的中文原因，不能只有状态码"


# 验证邮箱规范化：去除首尾空白并转为小写，保证唯一性比较大小写不敏感。
def test_normalize_email_strips_and_lowercases() -> None:
    assert normalize_email("  Foo.Bar@Example.COM ") == "foo.bar@example.com"


# 验证非法邮箱（空、缺 @、缺域名点、含空白、超长）统一返回 422 invalid_email。
@pytest.mark.parametrize(
    "raw",
    ["", "   ", "no-at-sign", "user@localhost", "a b@example.com", "x" * 250 + "@ex.com"],
)
def test_normalize_email_rejects_invalid_values(raw: str) -> None:
    with pytest.raises(AppError) as exc_info:
        normalize_email(raw)
    assert_app_error(exc_info, status=422, code="invalid_email")


# 验证显示名去除首尾空白，且 100 字符边界可接受。
def test_normalize_display_name_strips_and_accepts_100_chars() -> None:
    assert normalize_display_name("  小明  ") == "小明"
    assert normalize_display_name("名" * 100) == "名" * 100


# 验证空白或超过 100 字符的显示名返回 422 invalid_display_name。
@pytest.mark.parametrize("raw", ["", "   ", "名" * 101])
def test_normalize_display_name_rejects_blank_or_too_long(raw: str) -> None:
    with pytest.raises(AppError) as exc_info:
        normalize_display_name(raw)
    assert_app_error(exc_info, status=422, code="invalid_display_name")


# 验证密码策略的合法边界：10 与 128 字符、同时含字母和数字即可通过。
@pytest.mark.parametrize("password", ["abcdefghi1", "a1" * 64])
def test_validate_password_accepts_boundaries(password: str) -> None:
    validate_password(password, email="someone@example.com")


# 验证密码策略的拒绝分支：过短、过长、缺数字、缺字母、等于邮箱或邮箱本地部分。
@pytest.mark.parametrize(
    ("password", "email", "reason_fragment"),
    [
        ("abcdefgh1", "someone@example.com", "10"),
        ("a1" * 64 + "x", "someone@example.com", "128"),
        ("onlyletterspassword", "someone@example.com", "数字"),
        ("1234567890123", "someone@example.com", "字母"),
        ("Alice2026@Example.com", "alice2026@example.com", "邮箱"),
        ("ALICE2026PW", "alice2026pw@example.com", "邮箱"),
    ],
)
def test_validate_password_rejects_weak_passwords(
    password: str, email: str, reason_fragment: str
) -> None:
    with pytest.raises(AppError) as exc_info:
        validate_password(password, email=email)
    assert_app_error(exc_info, status=422, code="weak_password")
    assert reason_fragment in exc_info.value.detail, (
        f"weak_password 的 detail 必须说明未满足的规则（应包含“{reason_fragment}”），"
        f"实际：{exc_info.value.detail}"
    )


# 验证密码哈希使用 argon2id，不保存明文，且能校验正确/错误密码。
def test_hash_password_uses_argon2id_and_verifies() -> None:
    hashed = hash_password("Knowra-Pass-2026")

    assert hashed.startswith("$argon2id$")
    assert "Knowra-Pass-2026" not in hashed
    assert verify_password(hashed, "Knowra-Pass-2026") is True
    assert verify_password(hashed, "wrong-pass-2026") is False


# 验证损坏或非 argon2 的哈希不会抛异常，而是按校验失败处理。
def test_verify_password_returns_false_for_malformed_hash() -> None:
    assert verify_password("not-a-hash", "Knowra-Pass-2026") is False


# 验证哈希参数升级后，旧参数生成的哈希会被识别为需要重新哈希。
def test_needs_rehash_detects_outdated_parameters(monkeypatch) -> None:
    old_hash = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1).hash("Knowra-Pass-2026")
    monkeypatch.setattr(
        passwords, "_hasher", PasswordHasher(time_cost=2, memory_cost=16, parallelism=1)
    )

    assert needs_rehash(old_hash) is True
    assert needs_rehash(hash_password("Knowra-Pass-2026")) is False


# 验证角色权限矩阵：viewer 只读、member 可写、admin 额外可管理用户、未知角色无任何权限。
@pytest.mark.parametrize(
    ("role", "expected"),
    [
        ("viewer", ["knowledge:read"]),
        ("member", ["knowledge:read", "knowledge:write"]),
        ("admin", ["knowledge:read", "knowledge:write", "models:manage", "users:manage"]),
        ("root", []),
    ],
)
def test_permissions_for_role_matrix(role: str, expected: list[str]) -> None:
    assert permissions_for(role) == expected


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


# 验证登录限流：窗口内第 5 次失败后锁定，Retry-After 按最早失败时间计算，窗口滑出后解锁。
def test_login_rate_limiter_locks_after_max_failures_and_unlocks_after_window() -> None:
    clock = FakeClock()
    limiter = LoginRateLimiter(max_failures=5, window_seconds=900, clock=clock)

    for second in (0, 10, 20, 30):
        clock.now = second
        limiter.record_failure("alice@example.com")
        assert limiter.retry_after("alice@example.com") is None

    clock.now = 40
    limiter.record_failure("alice@example.com")
    clock.now = 50
    assert limiter.retry_after("alice@example.com") == 850
    assert limiter.retry_after("bob@example.com") is None, "限流必须按邮箱隔离"

    clock.now = 901
    assert limiter.retry_after("alice@example.com") is None


# 验证登录成功后重置失败计数，之前的失败不再累计。
def test_login_rate_limiter_reset_clears_failures() -> None:
    clock = FakeClock()
    limiter = LoginRateLimiter(max_failures=2, window_seconds=900, clock=clock)

    limiter.record_failure("alice@example.com")
    limiter.reset("alice@example.com")
    limiter.record_failure("alice@example.com")

    assert limiter.retry_after("alice@example.com") is None
