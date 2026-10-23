"""当前实例的有界只读依赖检查，不主动调用外部模型。"""

import asyncio
from time import monotonic

from psycopg import AsyncConnection
from sqlalchemy import text

from app.models.user import utc_now
from app.schemas.admin_operations import StatusComponent, SystemStatus


async def database_check(session, component):
    engine = session.get_bind()
    if engine.dialect.name != "postgresql":
        if component == "pgvector":
            return StatusComponent(
                name=component, status="unknown", detail="当前数据库不支持此检查"
            )
        session.execute(text("SELECT 1"))
        return StatusComponent(name=component, status="ok", detail="数据库可访问")
    args, kwargs = engine.dialect.create_connect_args(engine.url)
    # 连接建立、查询、取消及连接关闭都位于单项 2 秒截止时间内。
    async with await AsyncConnection.connect(
        *args, **(kwargs | {"connect_timeout": 2, "autocommit": True})
    ) as connection:
        if component == "database":
            await connection.execute("SELECT 1")
            return StatusComponent(name=component, status="ok", detail="数据库可访问")
        cursor = await connection.execute(
            "SELECT extversion FROM pg_extension WHERE extname='vector'"
        )
        installed = await cursor.fetchone()
        return StatusComponent(
            name=component,
            status="ok" if installed else "unavailable",
            detail="pgvector 已安装" if installed else "未检测到 pgvector 扩展",
        )


async def system_status(session, settings, readiness, shutdown, instance_id):
    components = []
    deadline = monotonic() + 5
    for name in ("database", "pgvector"):
        try:
            async with asyncio.timeout(min(2, max(0, deadline - monotonic()))):
                component = await database_check(session, name)
        except TimeoutError:
            component = StatusComponent(
                name=name, status="unavailable", detail="检查超时，请稍后重试"
            )
        except Exception:
            component = StatusComponent(
                name=name, status="unavailable", detail="依赖检查失败，请检查服务连接"
            )
        components.append(component)
    status = getattr(readiness, "status", "unknown")
    state = (
        "disabled"
        if not settings.document_model_bootstrap_enabled
        else {
            "ready": "ok",
            "loading": "degraded",
            "unavailable": "unavailable",
            "skipped": "unknown",
        }.get(status, "unknown")
    )
    if shutdown.is_shutting_down:
        state = "unavailable"
    components.append(
        StatusComponent(
            name="document_models", status=state, detail="仅代表当前服务进程的文档模型准备状态"
        )
    )
    components.append(
        StatusComponent(
            name="external_models",
            status="unknown",
            detail="不主动调用外部模型，请参考模型服务中的最近显式测试",
        )
    )
    return SystemStatus(checked_at=utc_now(), instance_id=instance_id, components=components)
