"""模型诊断短事务准入、请求内有界调用及原子结果审计。"""

import asyncio
import math
from dataclasses import dataclass, field
from datetime import timedelta
from time import monotonic
from uuid import UUID

import httpx
from sqlalchemy import text
from sqlmodel import Session, select

from app.core.config import Settings
from app.core.errors import AppError
from app.core.logging import get_logger
from app.core.trace_context import get_trace_id
from app.models.admin_operations import ModelProbeResult
from app.models.model_configuration import ModelProfile
from app.models.user import User, utc_now
from app.services.admin_audit import _record_failure, admin_operation
from app.services.model_configuration import _decrypt, _profile, probe_read
from app.services.model_probe_transport import ProbeTransport
from app.services.user_admin import lock_admins

logger = get_logger(__name__)


@dataclass(frozen=True)
class ProbeSnapshot:
    kind: str
    base_url: str
    model: str
    api_format: str | None
    dimensions: int | None
    api_key: str = field(repr=False)


def admit_probe(session, actor, profile_id, expected_revision, settings, shutdown):
    identity = dict(
        actor_user_id=actor.id,
        action="model.test",
        resource_type="model",
        resource_id=profile_id,
        trace_id=get_trace_id(),
    )
    try:
        if shutdown.is_shutting_down:
            raise AppError(503, "admin_dependency_unavailable", "应用正在关闭，请稍后再测试")
        lock_admins(session, actor)
        if session.get_bind().dialect.name == "postgresql":
            session.execute(text("SELECT pg_advisory_xact_lock(71022300)"))
        profile = _profile(session, profile_id)
        if profile.revision != expected_revision:
            raise AppError(409, "model_revision_conflict", "配置已更新，请刷新后测试当前版本")
        key = _decrypt(profile.api_key_encrypted, settings)
        now = utc_now()
        running = session.exec(
            select(ModelProbeResult).where(
                ModelProbeResult.status == "running", ModelProbeResult.lease_expires_at > now
            )
        ).all()
        latest = session.exec(
            select(ModelProbeResult)
            .where(ModelProbeResult.profile_id == profile_id)
            .order_by(ModelProbeResult.started_at.desc())
            .limit(1)
        ).first()
        cooldown = settings.admin_model_test_cooldown_seconds
        wait = 0
        if latest:
            from datetime import UTC

            started = latest.started_at
            if started.tzinfo is None:
                started = started.replace(tzinfo=UTC)
            wait = math.ceil(cooldown - (now - started).total_seconds())
        if wait > 0 or len(running) >= settings.admin_model_test_max_concurrent:
            raise AppError(
                429,
                "model_test_rate_limited",
                "测试正在冷却或并发已满，请稍后重试",
                headers={"Retry-After": str(max(1, wait))},
            )
        snapshot = ProbeSnapshot(
            kind=profile.kind,
            base_url=profile.base_url,
            model=profile.model,
            api_format=profile.api_format,
            dimensions=profile.dimensions,
            api_key=key,
        )
        row = ModelProbeResult(
            profile_id=profile_id,
            profile_revision=profile.revision,
            actor_user_id=actor.id,
            trace_id=get_trace_id(),
            lease_expires_at=now + timedelta(seconds=settings.admin_model_test_timeout_seconds + 2),
        )
        probe_id = row.id
        session.add(row)
        session.commit()
        return probe_id, snapshot
    except AppError as error:
        session.rollback()
        _record_failure(session, identity, error)
        raise
    except Exception:
        session.rollback()
        raise AppError(503, "admin_dependency_unavailable", "模型诊断依赖暂不可用") from None


def _payload(snapshot):
    if snapshot.kind == "embedding":
        return "/embeddings", {
            "model": snapshot.model,
            "input": ["Knowra connection test."],
            "dimensions": snapshot.dimensions,
            "encoding_format": "float",
        }
    if snapshot.kind == "rerank":
        fields = {
            "query": "What is a knowledge base?",
            "documents": ["A collection of knowledge.", "The weather is sunny."],
        }
        if snapshot.api_format == "dashscope":
            return "/services/rerank/text-rerank/text-rerank", {
                "model": snapshot.model,
                "input": fields,
                "parameters": {"top_n": 2, "return_documents": False},
            }
        return "/rerank", {"model": snapshot.model, **fields, "top_n": 2, "return_documents": False}
    return "/chat/completions", {
        "model": snapshot.model,
        "messages": [{"role": "user", "content": "Reply with OK."}],
        "stream": False,
        "max_tokens": 16,
    }


def _valid_output(snapshot, body):
    try:
        if snapshot.kind == "embedding":
            vector = body["data"][0]["embedding"]
            return len(vector) == snapshot.dimensions and all(
                type(v) in (int, float) and math.isfinite(v) for v in vector
            )
        if snapshot.kind == "rerank":
            rows = (body["output"] if snapshot.api_format == "dashscope" else body)["results"]
            return (
                bool(rows)
                and len(rows) == 2
                and len({r["index"] for r in rows}) == len(rows)
                and all(
                    type(r["index"]) is int
                    and 0 <= r["index"] < 2
                    and type(r["relevance_score"]) in (int, float)
                    and math.isfinite(r["relevance_score"])
                    and 0 <= r["relevance_score"] <= 1
                    for r in rows
                )
            )
        return isinstance(body["choices"][0]["message"]["content"], str) and bool(
            body["choices"][0]["message"]["content"].strip()
        )
    except KeyError, TypeError, IndexError, ValueError:
        return False


async def execute_probe(snapshot, timeout):
    path, payload = _payload(snapshot)
    try:
        async with asyncio.timeout(timeout):
            async with httpx.AsyncClient(
                transport=ProbeTransport(), timeout=timeout, follow_redirects=False, trust_env=False
            ) as client:
                # 有界流式读取，既不持久化也不向调用者返回上游输出。
                async with client.stream(
                    "POST",
                    snapshot.base_url.rstrip("/") + path,
                    json=payload,
                    headers={"Authorization": f"Bearer {snapshot.api_key}"}
                    if snapshot.api_key
                    else {},
                ) as response:
                    if response.status_code in (401, 403):
                        return "model_test_auth_failed"
                    if response.status_code != 200:
                        return "model_test_failed"
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > 1_048_576:
                            return "model_test_invalid_response"
                    import json

                    try:
                        body = json.loads(data)
                    except ValueError, UnicodeError:
                        return "model_test_invalid_response"
                    return (
                        "model_test_passed"
                        if _valid_output(snapshot, body)
                        else "model_test_invalid_response"
                    )
    except TimeoutError, httpx.TimeoutException:
        return "model_test_timeout"
    except httpx.NetworkError:
        return "model_test_unreachable"
    except Exception:
        return "model_test_failed"


def finish_probe(session, actor, profile_id, probe_id, status, code, latency):
    with admin_operation(session, actor, "model.test", profile_id) as audit:
        row = session.get(ModelProbeResult, probe_id, populate_existing=True)
        row.status, row.code, row.latency_ms = status, code, latency
        row.finished_at = row.lease_expires_at = utc_now()
        session.add(row)
        audit.values.update(
            profile_revision=row.profile_revision, status=status, code=code, latency_ms=latency
        )
    session.refresh(row)
    profile = session.get(ModelProfile, profile_id, populate_existing=True)
    return probe_read(row, profile)


async def run_probe(
    session: Session,
    actor: User,
    profile_id: UUID,
    expected_revision: int,
    settings: Settings,
    shutdown,
):
    probe_id, snapshot = admit_probe(
        session, actor, profile_id, expected_revision, settings, shutdown
    )
    started = monotonic()
    completed = False
    try:
        code = await execute_probe(snapshot, settings.admin_model_test_timeout_seconds)
        status = "passed" if code == "model_test_passed" else "failed"
        if shutdown.is_shutting_down:
            status, code = "interrupted", "model_test_interrupted"
        result = finish_probe(
            session,
            actor,
            profile_id,
            probe_id,
            status,
            code,
            round((monotonic() - started) * 1000, 2),
        )
        completed = True
        return result
    finally:
        if not completed:
            # 取消、审计故障或异常均释放租约；强杀由到期租约表达未知。
            try:
                session.rollback()
                row = session.get(ModelProbeResult, probe_id, populate_existing=True)
                if row and row.status == "running":
                    try:
                        finish_probe(
                            session,
                            actor,
                            profile_id,
                            probe_id,
                            "interrupted",
                            "model_test_interrupted",
                            round((monotonic() - started) * 1000, 2),
                        )
                    except AppError:
                        # 审计依赖故障仍需释放运行名额，保留未知而非通过结果。
                        session.rollback()
                        row = session.get(ModelProbeResult, probe_id, populate_existing=True)
                        row.status, row.code = "interrupted", "model_test_interrupted"
                        row.finished_at = row.lease_expires_at = utc_now()
                        session.add(row)
                        session.commit()
            except Exception:
                session.rollback()
                logger.warning(
                    "模型诊断清理失败", probe_id=str(probe_id), profile_id=str(profile_id)
                )
