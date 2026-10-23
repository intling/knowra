"""系统模型配置管理、加密与不可变运行时快照。"""

from datetime import UTC, timedelta
from uuid import UUID, uuid4

from cryptography.fernet import Fernet, InvalidToken
from pydantic import ValidationError
from sqlmodel import Session, func, select

from app.core.config import Settings
from app.core.errors import AppError
from app.core.logging import get_logger
from app.models.admin_operations import ModelProbeResult
from app.models.document_embedding import DocumentEmbeddingJob
from app.models.model_configuration import MODEL_KINDS, ModelBinding, ModelProfile
from app.models.user import User, utc_now
from app.schemas.model_configuration import (
    EffectiveModel,
    ModelCreate,
    ModelPage,
    ModelProbeRead,
    ModelRead,
    ModelUpdate,
)
from app.services.admin_audit import admin_operation
from app.services.user_admin import lock_admins

logger = get_logger(__name__)


def _cipher(settings: Settings) -> Fernet:
    try:
        return Fernet(settings.model_config_encryption_key.encode())
    except ValueError, TypeError:
        raise AppError(
            503,
            "model_secret_unavailable",
            "模型密钥加密配置不可用，请配置有效的 MODEL_CONFIG_ENCRYPTION_KEY",
        ) from None


def _decrypt(value: str | None, settings: Settings) -> str:
    if not value:
        return ""
    try:
        return _cipher(settings).decrypt(value.encode()).decode()
    except InvalidToken, UnicodeError:
        raise AppError(
            503, "model_secret_unavailable", "无法解密模型密钥，请恢复加密主密钥或重新录入"
        ) from None


def lock_model_binding(session: Session, kind: str) -> ModelBinding:
    # 空绑定只会出现在测试 create_all 或新数据库；正常部署由迁移预建四行。
    if session.get_bind().dialect.name == "postgresql":
        from sqlalchemy import text

        session.execute(
            text("SELECT pg_advisory_xact_lock(:key)"), {"key": 71022100 + MODEL_KINDS.index(kind)}
        )
    binding = session.exec(
        select(ModelBinding)
        .where(ModelBinding.kind == kind)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).first()
    if binding is None:
        binding = ModelBinding(kind=kind)
        session.add(binding)
        session.flush()
    return binding


def _profile(session: Session, profile_id: UUID) -> ModelProfile:
    profile = session.exec(
        select(ModelProfile)
        .where(ModelProfile.id == profile_id)
        .execution_options(populate_existing=True)
    ).first()
    if profile is None:
        raise AppError(404, "model_not_found", "模型配置不存在")
    return profile


def public_profile(session: Session, profile: ModelProfile) -> ModelRead:
    binding = session.get(ModelBinding, profile.kind)
    return ModelRead(
        **profile.model_dump(exclude={"api_key_encrypted"}),
        is_default=bool(binding and binding.profile_id == profile.id),
        has_api_key=bool(profile.api_key_encrypted),
    )


def list_profiles(session: Session, *, offset: int, limit: int, kind: str | None) -> ModelPage:
    query = select(ModelProfile)
    count = select(func.count()).select_from(ModelProfile)
    if kind:
        query = query.where(ModelProfile.kind == kind)
        count = count.where(ModelProfile.kind == kind)
    profiles = session.exec(
        query.order_by(ModelProfile.created_at, ModelProfile.id).offset(offset).limit(limit)
    ).all()
    return ModelPage(
        items=[public_profile(session, p) for p in profiles],
        total=session.exec(count).one(),
        offset=offset,
        limit=limit,
    )


def create_profile(
    session: Session, actor: User, payload: ModelCreate, settings: Settings
) -> ModelRead:
    profile_id = uuid4()
    with admin_operation(session, actor, "model.create", profile_id) as audit:
        lock_admins(session, actor)
        key = payload.api_key.get_secret_value()
        encrypted = _cipher(settings).encrypt(key.encode()).decode() if key else None
        profile = ModelProfile(
            id=profile_id,
            **payload.model_dump(exclude={"api_key"}),
            api_key_encrypted=encrypted,
        )
        session.add(profile)
        audit.capture(
            {},
            profile.model_dump(exclude={"api_key_encrypted"}),
            secret_changed=bool(encrypted),
            endpoint_changed=True,
        )
    session.refresh(profile)
    logger.info(
        "管理员创建模型配置",
        profile_id=str(profile.id),
        actor_user_id=str(actor.id),
        kind=profile.kind,
    )
    return public_profile(session, profile)


def _embedding_identity(session: Session, settings: Settings) -> tuple:
    binding = session.get(ModelBinding, "embedding")
    profile = (
        session.get(ModelProfile, binding.profile_id) if binding and binding.profile_id else None
    )
    if profile:
        return profile.base_url.rstrip("/"), profile.model, profile.dimensions
    return (
        settings.document_embedding_api_base_url.rstrip("/"),
        settings.document_embedding_model,
        settings.document_embedding_dimensions,
    )


def guard_embedding_change(
    session: Session, settings: Settings, candidate: ModelProfile | None
) -> None:
    current = _embedding_identity(session, settings)
    proposed = (
        (candidate.base_url.rstrip("/"), candidate.model, candidate.dimensions)
        if candidate
        else (
            settings.document_embedding_api_base_url.rstrip("/"),
            settings.document_embedding_model,
            settings.document_embedding_dimensions,
        )
    )
    if current == proposed:
        return
    protected = session.exec(
        select(DocumentEmbeddingJob.id)
        .join(User, User.id == DocumentEmbeddingJob.owner_user_id)
        .where(
            User.deleted_at.is_(None),
            DocumentEmbeddingJob.status.in_(("succeeded", "queued", "running")),
        )
        .limit(1)
    ).first()
    if protected is not None:
        raise AppError(
            409,
            "embedding_index_conflict",
            "已有向量索引或运行中任务，切换 Embedding 模型需要先规划重建索引",
        )


def update_profile(
    session: Session, actor: User, profile_id: UUID, payload: ModelUpdate, settings: Settings
) -> ModelRead:
    with admin_operation(session, actor, "model.update", profile_id) as audit:
        lock_admins(session, actor)
        profile = _profile(session, profile_id)
        binding = lock_model_binding(session, profile.kind)
        changes = payload.model_dump(exclude_unset=True, exclude={"api_key", "clear_api_key"})
        key = payload.api_key.get_secret_value()
        if (
            not changes
            and not key
            and not payload.clear_api_key
            and "api_key" not in payload.model_fields_set
        ):
            raise AppError(422, "empty_update", "请至少提供一项模型配置变更")
        is_default = binding.profile_id == profile.id
        if is_default and changes.get("enabled") is False:
            raise AppError(409, "model_in_use", "请先切换默认模型或恢复环境配置，再禁用")
        fields = {
            key: getattr(profile, key)
            for key in (
                "kind",
                "name",
                "base_url",
                "model",
                "enabled",
                "timeout_seconds",
                "max_retries",
                "dimensions",
                "api_format",
            )
        }
        # 先完整验证更新后的用途字段，任何失败均不产生部分写入。
        try:
            validated = ModelCreate.model_validate(fields | changes)
        except ValidationError:
            raise AppError(
                422, "invalid_model_configuration", "模型用途与维度或重排协议不匹配"
            ) from None
        candidate = ModelProfile(**validated.model_dump(exclude={"api_key"}))
        if is_default and profile.kind == "embedding":
            guard_embedding_change(session, settings, candidate)
        encrypted = (
            _cipher(settings).encrypt(key.encode()).decode() if key else profile.api_key_encrypted
        )
        if payload.clear_api_key:
            encrypted = None
        before = profile.model_dump(exclude={"api_key_encrypted"})
        secret_changed = profile.api_key_encrypted != encrypted
        endpoint_changed = profile.base_url != validated.base_url
        for field, value in validated.model_dump(exclude={"api_key"}).items():
            setattr(profile, field, value)
        profile.api_key_encrypted = encrypted
        profile.revision += 1
        profile.updated_at = utc_now()
        if is_default:
            binding.revision += 1
            session.add(binding)
        session.add(profile)
        audit.capture(
            before,
            profile.model_dump(exclude={"api_key_encrypted"}),
            secret_changed=secret_changed,
            endpoint_changed=endpoint_changed,
        )
    logger.info("管理员更新模型配置", profile_id=str(profile.id), actor_user_id=str(actor.id))
    return public_profile(session, profile)


def change_binding(
    session: Session, actor: User, profile_id: UUID, settings: Settings, *, activate: bool
) -> ModelRead:
    action = "model.activate" if activate else "model.deactivate"
    with admin_operation(session, actor, action, profile_id) as audit:
        lock_admins(session, actor)
        profile = _profile(session, profile_id)
        binding = lock_model_binding(session, profile.kind)
        if activate and not profile.enabled:
            raise AppError(409, "model_disabled", "禁用的模型配置不能设为默认")
        if not activate and binding.profile_id != profile.id:
            raise AppError(409, "model_not_active", "该配置不是当前默认模型")
        if profile.kind == "embedding":
            guard_embedding_change(session, settings, profile if activate else None)
        before = {"default_profile_id": binding.profile_id, "binding_revision": binding.revision}
        binding.profile_id = profile.id if activate else None
        binding.revision += 1
        session.add(binding)
        audit.capture(
            before, {"default_profile_id": binding.profile_id, "binding_revision": binding.revision}
        )
    logger.info(
        "管理员切换默认模型",
        profile_id=str(profile.id),
        actor_user_id=str(actor.id),
        kind=profile.kind,
        activate=activate,
    )
    return public_profile(session, profile)


def delete_profile(session: Session, actor: User, profile_id: UUID) -> None:
    with admin_operation(session, actor, "model.delete", profile_id) as audit:
        lock_admins(session, actor)
        profile = _profile(session, profile_id)
        binding = lock_model_binding(session, profile.kind)
        if binding.profile_id == profile.id:
            raise AppError(409, "model_in_use", "请先切换默认模型或恢复环境配置，再删除")
        audit.capture(
            profile.model_dump(exclude={"api_key_encrypted"}),
            {},
            secret_changed=bool(profile.api_key_encrypted),
            endpoint_changed=True,
        )
        session.delete(profile)
    logger.info("管理员删除模型配置", profile_id=str(profile_id), actor_user_id=str(actor.id))


PROBE_DETAILS = {
    "model_test_passed": "连接与协议检查通过",
    "model_test_timeout": "模型服务响应超时",
    "model_test_auth_failed": "模型服务拒绝鉴权，请检查密钥",
    "model_test_unreachable": "无法连接模型服务",
    "model_test_invalid_response": "模型响应格式或向量维度不符合要求",
    "model_test_failed": "模型服务测试未通过",
    "model_test_interrupted": "测试已中断，无法确认结果",
    "model_test_running": "测试正在进行",
}


def probe_read(row: ModelProbeResult, profile: ModelProfile | None) -> ModelProbeRead:
    now = utc_now()
    expiry = (
        row.lease_expires_at.replace(tzinfo=UTC)
        if row.lease_expires_at.tzinfo is None
        else row.lease_expires_at
    )
    status = "interrupted" if row.status == "running" and expiry <= now else row.status
    code = row.code or (
        "model_test_interrupted" if status == "interrupted" else "model_test_running"
    )
    code = code if code in PROBE_DETAILS else "model_test_failed"
    checked = row.finished_at or row.started_at
    checked = checked.replace(tzinfo=UTC) if checked.tzinfo is None else checked
    return ModelProbeRead(
        probe_id=row.id,
        status=status,
        code=code,
        detail=PROBE_DETAILS[code],
        latency_ms=row.latency_ms,
        checked_at=checked,
        config_revision=row.profile_revision,
        is_current=bool(
            profile
            and row.profile_revision == profile.revision
            and status in {"passed", "failed"}
            and now - timedelta(minutes=15) <= checked <= now
        ),
    )


def effective_models(session: Session, settings: Settings) -> list[EffectiveModel]:
    result = []
    for kind in MODEL_KINDS:
        binding = session.get(ModelBinding, kind, populate_existing=True)
        profile = (
            session.get(ModelProfile, binding.profile_id, populate_existing=True)
            if binding and binding.profile_id
            else None
        )
        prefix = "document_embedding" if kind == "embedding" else kind
        enabled = (
            profile.enabled
            if profile
            else (True if kind == "chat" else getattr(settings, f"{prefix}_enabled"))
        )
        model = profile.model if profile else getattr(settings, f"{prefix}_model")
        endpoint = profile.base_url if profile else getattr(settings, f"{prefix}_api_base_url")
        available = bool(model and endpoint)
        if profile:
            try:
                _decrypt(profile.api_key_encrypted, settings)
            except AppError:
                available = False
        latest = (
            session.exec(
                select(ModelProbeResult)
                .where(ModelProbeResult.profile_id == profile.id)
                .order_by(ModelProbeResult.started_at.desc(), ModelProbeResult.id.desc())
                .limit(1)
            ).first()
            if profile
            else None
        )
        result.append(
            EffectiveModel(
                kind=kind,
                source="profile" if profile else "environment",
                enabled=enabled,
                profile_id=profile.id if profile else None,
                model=model,
                profile_revision=profile.revision if profile else None,
                binding_revision=binding.revision if binding else 0,
                configuration_status="disabled"
                if not enabled
                else "ok"
                if available
                else "unavailable",
                latest_probe=probe_read(latest, profile) if latest else None,
            )
        )
    return result


def resolve_model_settings(session: Session, settings: Settings) -> Settings:
    rows = session.exec(
        select(ModelBinding, ModelProfile)
        .outerjoin(ModelProfile, ModelProfile.id == ModelBinding.profile_id)
        .order_by(ModelBinding.kind)
        .execution_options(populate_existing=True)
    ).all()
    updates, configured = {}, []
    versions = []
    for binding, profile in rows:
        if binding.revision:
            versions.append(f"{binding.kind}:{binding.revision}")
        if profile is None:
            continue
        configured.append(profile.kind)
        prefix = "document_embedding" if profile.kind == "embedding" else profile.kind
        updates.update(
            {
                f"{prefix}_api_base_url": profile.base_url,
                f"{prefix}_api_key": _decrypt(profile.api_key_encrypted, settings),
                f"{prefix}_model": profile.model,
            }
        )
        timeout_key = (
            f"{prefix}_timeout" if profile.kind == "query_rewrite" else f"{prefix}_request_timeout"
        )
        updates[timeout_key] = profile.timeout_seconds
        if profile.kind != "rerank":
            updates[f"{prefix}_max_retries"] = profile.max_retries
        if profile.kind in ("rerank", "query_rewrite", "embedding"):
            updates[f"{prefix}_enabled"] = True
        if profile.kind == "embedding":
            updates["document_embedding_dimensions"] = profile.dimensions
        if profile.kind == "rerank":
            updates["rerank_api_format"] = profile.api_format
    if versions:
        updates["model_configuration_revision"] = "|".join(versions)
    if configured:
        updates["configured_model_kinds"] = tuple(configured)
    return settings.model_copy(update=updates)
