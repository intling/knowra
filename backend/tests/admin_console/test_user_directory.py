"""后台改版第三批 RED：全量账号搜索、组合筛选和只读运行详情。"""

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlmodel import select

from app.models.admin_operations import AdminAuditEvent
from app.models.chat_quota import ChatUsage, UserChatLimit
from app.models.user import UserCredential, UserSession
from tests.admin_console.helpers import assert_error, assert_status
from tests.auth_helpers import issue_session_token, login_as, make_account, seed_knowledge_chain

USER_FIELDS = {
    "id",
    "display_name",
    "email",
    "avatar_url",
    "status",
    "role",
    "deleted_at",
    "created_at",
    "updated_at",
    "permissions",
}
LIMIT_FIELDS = {"hourly_limit", "occupied_slots", "remaining", "window_seconds", "observed_at"}


@pytest.fixture
def directory(auth_db, admin_actor):
    # 覆盖邮箱、中文显示名、大小写、字面通配符、角色/状态及软删除，时间固定便于检验排序。
    data = [
        ("alice", "alice.lab@example.com", "Alpha 学习组", "member", "active", False),
        ("bob", "bob.team@example.com", "alpha 第二组", "member", "disabled", False),
        ("carol", "carol@example.com", "ALPHA 只读组", "viewer", "active", False),
        ("dana", "dana@example.com", "Beta 团队", "admin", "active", False),
        ("percent", "percent@example.com", "进度 100% 达成", "viewer", "disabled", False),
        ("underscore", "underscore@example.com", "编号 A_B", "member", "active", False),
        ("slash", "slash@example.com", r"路径 A\B", "member", "active", False),
        ("deleted", "deleted@example.com", "Alpha 已删除组", "member", "active", True),
    ]
    rows = {}
    for index, (key, email, name, role, status, deleted) in enumerate(data):
        rows[key] = make_account(
            auth_db,
            email=email,
            display_name=name,
            role=role,
            status=status,
            deleted=deleted,
            created_at=datetime(2026, 10, 1, tzinfo=UTC) + timedelta(minutes=index),
        )
    return rows


def page(client, params, condition):
    result = assert_status(client.get("/api/admin/users", params=params), 200, condition)
    assert set(result) == {"items", "total", "offset", "limit"}, "账号查询必须保留原分页结构。"
    for user in result["items"]:
        assert set(user) == USER_FIELDS, (
            "账号列表只能返回原 UserRead 字段，不能附带运行材料或资料。"
        )
    return result


# 验证邮箱/中文名称的大小写不敏感子串查询，百分号、下划线、反斜杠和 SQL 片段均按字面处理。
@pytest.mark.parametrize(
    "query,expected",
    [
        ("ALICE.LAB", ["alice"]),
        ("aLpHa", ["alice", "bob", "carol"]),
        ("学习组", ["alice"]),
        ("  ALPHA  ", ["alice", "bob", "carol"]),
        ("%", ["percent"]),
        ("_", ["underscore"]),
        ("\\", ["slash"]),
        ("100%", ["percent"]),
        ("does-not-exist", []),
        ("' OR 1=1 --", []),
    ],
)
def test_search_matches_literal_substrings(auth_client, directory, query, expected):
    body = page(auth_client, {"q": query}, f"搜索 {query!r} 应匹配全量账号的邮箱或名称")
    assert [row["id"] for row in body["items"]] == [str(directory[key].id) for key in expected], (
        "账号搜索没有按字面子串匹配，或把软删除账号/未匹配账号混入结果。"
    )
    assert body["total"] == len(expected), "搜索总数必须是全量匹配数，不能使用未筛选账号总数。"


# 验证三种角色与两种账号状态的独立筛选，包括禁用账号且持续排除软删除账号。
@pytest.mark.parametrize(
    "params,expected",
    [
        ({"role": "admin"}, ["dana", "actor"]),
        ({"role": "member"}, ["alice", "bob", "underscore", "slash"]),
        ({"role": "viewer"}, ["carol", "percent"]),
        ({"status": "active"}, ["alice", "carol", "dana", "underscore", "slash", "actor"]),
        ({"status": "disabled"}, ["bob", "percent"]),
    ],
)
def test_role_and_status_filters(auth_client, directory, admin_actor, params, expected):
    rows = directory | {"actor": admin_actor}
    body = page(auth_client, params, f"账号筛选 {params} 应在分页前执行")
    assert [item["id"] for item in body["items"]] == [str(rows[key].id) for key in expected]
    assert body["total"] == len(expected)


# 验证邮箱/名称的 OR 搜索与角色、状态按 AND 组合，未匹配时返回 200 空页。
@pytest.mark.parametrize(
    "params,expected",
    [
        ({"q": "alpha", "role": "member", "status": "active"}, ["alice"]),
        ({"q": "alpha", "role": "member", "status": "disabled"}, ["bob"]),
        ({"q": "alpha", "role": "viewer", "status": "disabled"}, []),
    ],
)
def test_filters_are_combined_with_and(auth_client, directory, params, expected):
    body = page(auth_client, params, "搜索、角色、状态必须同时满足")
    assert [item["id"] for item in body["items"]] == [str(directory[key].id) for key in expected]
    assert body["total"] == len(expected)


# 验证匹配记录位于默认第一页之外时仍可检索，总数和 offset 基于筛选后的全量结果。
def test_search_filters_before_pagination_and_uses_uuid_tiebreak(auth_client, auth_db, admin_actor):
    timestamp = datetime(2026, 10, 1, tzinfo=UTC)
    for index in range(22):
        make_account(auth_db, email=f"filler-{index}@example.com", created_at=timestamp)
    matching = [
        make_account(
            auth_db,
            display_name=f"目标小组 {index}",
            role="member",
            created_at=timestamp + timedelta(days=1),
        )
        for index in range(3)
    ]
    ordered_ids = sorted(str(user.id) for user in matching)
    body = page(
        auth_client,
        {"q": "目标小组", "role": "member", "offset": 1, "limit": 1},
        "超过默认第一页的账号也应可搜索，并在相同创建时间按 UUID 排序",
    )
    assert body["total"] == 3 and body["offset"] == 1 and body["limit"] == 1
    assert [item["id"] for item in body["items"]] == ordered_ids[1:2]
    empty = page(auth_client, {"q": "目标小组", "offset": 3, "limit": 1}, "越过匹配结果末页应为空")
    assert empty["total"] == 3 and empty["items"] == []


# 验证省略搜索、空串与纯空白兼容旧列表行为，保持稳定排序及完整总数。
@pytest.mark.parametrize("params", [{}, {"q": ""}, {"q": "   "}])
def test_empty_search_preserves_original_list(auth_client, directory, admin_actor, params):
    body = page(auth_client, params, "空搜索应保留原列表契约")
    visible = [row for key, row in directory.items() if key != "deleted"] + [admin_actor]
    assert [item["id"] for item in body["items"]] == [str(user.id) for user in visible]
    assert body["total"] == len(visible)


# 验证查询长度上限按字符计数，100 个中文字符仍是合法搜索而非按 UTF-8 字节误拒绝。
def test_search_accepts_exactly_one_hundred_unicode_characters(auth_client, auth_db, admin_actor):
    query = "测" * 100
    target = make_account(auth_db, display_name=query)
    body = page(auth_client, {"q": query}, "100 字符查询应可检索对应账号")
    assert body["total"] == 1 and body["items"][0]["id"] == str(target.id)


# 验证超长搜索、非法角色/状态和分页参数均返回有原因的 422，不静默忽略筛选。
@pytest.mark.parametrize(
    "params",
    [
        {"q": "a" * 101},
        {"q": "测" * 101},
        {"q": " " * 101},
        {"role": "root"},
        {"role": ""},
        {"status": "deleted"},
        {"status": ""},
        {"offset": -1},
        {"limit": 0},
        {"limit": 101},
        {"limit": "invalid"},
    ],
)
def test_invalid_directory_query_has_clear_validation_error(auth_client, admin_actor, params):
    body = assert_status(
        auth_client.get("/api/admin/users", params=params),
        422,
        f"非法账号筛选 {list(params)} 应明确拒绝，不能返回未筛选数据",
    )
    assert body.get("detail"), "筛选失败必须包含参数错误原因。"


# 验证详情只计算目标未过期未撤销会话，不计入其他账号的会话，读取不撤销或延长任何会话。
def test_detail_counts_only_live_target_sessions(auth_client, auth_db, admin_actor):
    target = make_account(auth_db)
    for _ in range(4):
        issue_session_token(auth_db, target)
    sessions = auth_db.exec(
        select(UserSession)
        .where(UserSession.user_id == target.id)
        .order_by(UserSession.created_at, UserSession.id)
    ).all()
    sessions[2].expires_at = datetime.now(UTC) - timedelta(minutes=1)
    sessions[3].revoked_at = datetime.now(UTC)
    auth_db.add_all(sessions)
    another = make_account(auth_db)
    issue_session_token(auth_db, another)
    auth_db.commit()
    before = [(row.id, row.expires_at, row.revoked_at) for row in sessions]
    body = assert_status(
        auth_client.get(f"/api/admin/users/{target.id}"),
        200,
        "管理员应能查看账号运行详情，现有列表不能替代详情接口",
    )
    assert set(body) == {"user", "active_session_count", "chat_limit"}
    assert set(body["user"]) == USER_FIELDS and body["user"]["id"] == str(target.id)
    assert body["active_session_count"] == 2, "详情会话数必须排除过期、撤销及其他账号的会话。"
    for row in sessions:
        auth_db.refresh(row)
    assert [(row.id, row.expires_at, row.revoked_at) for row in sessions] == before
    assert not auth_db.exec(select(AdminAuditEvent)).all(), "只读详情不能生成管理写操作事件。"


# 验证禁用但未删除账号仍可查看详情，自身详情使用同一公开字段与当前会话统计。
@pytest.mark.parametrize("target_kind", ["disabled", "self"])
def test_detail_supports_disabled_accounts_and_current_admin(
    auth_client, auth_db, admin_actor, target_kind
):
    target = admin_actor if target_kind == "self" else make_account(auth_db, status="disabled")
    body = assert_status(
        auth_client.get(f"/api/admin/users/{target.id}"),
        200,
        "禁用账号和当前管理员均属于可管理的有效记录",
    )
    assert body["user"]["id"] == str(target.id) and body["user"]["status"] == target.status
    assert body["active_session_count"] == (1 if target_kind == "self" else 0)


# 验证详情额度按目标最近 60 分钟的预留计算，不限额为 null，超占时剩余为零，读取不清理旧预留。
@pytest.mark.parametrize("hourly_limit", [None, 1, 3])
def test_detail_includes_readonly_rolling_quota_snapshot(
    auth_client, auth_db, admin_actor, hourly_limit
):
    target = make_account(auth_db)
    another = make_account(auth_db)
    now = datetime.now(UTC)
    if hourly_limit is not None:
        auth_db.add(UserChatLimit(user_id=target.id, hourly_limit=hourly_limit))
    auth_db.add_all(
        [
            ChatUsage(user_id=target.id, created_at=now - timedelta(minutes=1)),
            ChatUsage(user_id=target.id, created_at=now - timedelta(minutes=30)),
            ChatUsage(user_id=target.id, created_at=now - timedelta(hours=2)),
            ChatUsage(user_id=another.id, created_at=now),
        ]
    )
    auth_db.commit()
    ids_before = {row.id for row in auth_db.exec(select(ChatUsage)).all()}
    body = assert_status(
        auth_client.get(f"/api/admin/users/{target.id}"), 200, "账号详情必须提供只读额度快照"
    )
    quota = body["chat_limit"]
    assert set(quota) == LIMIT_FIELDS and quota["window_seconds"] == 3600
    expected = (
        (None, None, None) if hourly_limit is None else (hourly_limit, 2, max(0, hourly_limit - 2))
    )
    assert (quota["hourly_limit"], quota["occupied_slots"], quota["remaining"]) == expected
    observed = datetime.fromisoformat(quota["observed_at"])
    assert observed.tzinfo is not None and now <= observed <= datetime.now(UTC)
    assert {row.id for row in auth_db.exec(select(ChatUsage)).all()} == ids_before, (
        "只读额度详情不能清理、补记或释放预留。"
    )


# 验证详情不返回密码/哈希、令牌材料、文件名、路径、私有片段和向量，管理员仍不能读他人正文。
def test_detail_cannot_expose_auth_material_or_private_knowledge(
    auth_client, auth_db, admin_actor, tmp_path
):
    target = make_account(auth_db)
    token = issue_session_token(auth_db, target)
    credential = auth_db.get(UserCredential, target.id)
    stored_session = auth_db.exec(select(UserSession).where(UserSession.user_id == target.id)).one()
    upload, parsed, _job, chunks, _embeddings = seed_knowledge_chain(
        auth_db, tmp_path, target, vectors=1
    )
    body = assert_status(
        auth_client.get(
            f"/api/admin/users/{target.id}",
            params={
                "owner_user_id": str(admin_actor.id),
            },
        ),
        200,
        "伪造归属参数不能让账号详情携带私有资料或认证材料",
    )
    assert set(body) == {"user", "active_session_count", "chat_limit"}
    assert set(body["user"]) == USER_FIELDS and set(body["chat_limit"]) == LIMIT_FIELDS
    stored = json.dumps(body, ensure_ascii=False)
    for private in [
        token,
        stored_session.token_hash,
        credential.password_hash,
        upload.original_filename,
        upload.storage_key,
        chunks[0].text,
        chunks[0].contextualized_text,
        str(parsed.id),
    ]:
        assert private not in stored, "用户运行详情超出安全投影，暴露了凭据或私有知识内容。"
    assert auth_client.get("/api/parsed-documents").json() == [], "管理权限不应扩大资料可见范围。"


# 验证已删除及不存在账号返回明确的 user_not_found，不因历史会话或资料而恢复可见性。
@pytest.mark.parametrize("deleted", [False, True])
def test_missing_or_deleted_detail_has_business_reason(auth_client, auth_db, admin_actor, deleted):
    user_id = make_account(auth_db, deleted=True).id if deleted else uuid4()
    assert_error(
        auth_client.get(f"/api/admin/users/{user_id}"),
        404,
        "user_not_found",
        "不存在或软删除账号不能出现在详情中",
    )


# 验证非法用户 UUID 在读取前有明确的参数错误，不能笼统返回无原因的 404。
def test_invalid_detail_id_has_validation_reason(auth_client, admin_actor):
    body = assert_status(
        auth_client.get("/api/admin/users/not-a-uuid"), 422, "账号详情 ID 必须校验 UUID 格式"
    )
    assert body.get("detail"), "非法账号标识必须说明参数错误原因。"


# 验证匿名、成员和只读角色均不可获得列表筛选或详情；客户端 role 参数不能提升真实权限。
@pytest.mark.parametrize("role", [None, "member", "viewer"])
@pytest.mark.parametrize("endpoint", ["list", "detail"])
def test_directory_reads_require_authenticated_admin(auth_client, auth_db, role, endpoint):
    target = make_account(auth_db)
    if role is None:
        auth_client.cookies.clear()
    else:
        login_as(auth_client, auth_db, make_account(auth_db, role=role))
    path = "/api/admin/users" if endpoint == "list" else f"/api/admin/users/{target.id}"
    assert_error(
        auth_client.get(path, params={"q": target.email, "role": "admin"}),
        401 if role is None else 403,
        "auth_required" if role is None else "forbidden",
        "账号列表和运行详情必须由服务端 users:manage 权限保护",
    )
