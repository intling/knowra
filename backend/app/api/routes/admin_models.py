"""仅管理员可使用的模型配置入口。"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from app.api.deps import SessionDep, require_permission
from app.core.config import Settings, get_settings
from app.core.permissions import MODELS_MANAGE
from app.models.user import User
from app.schemas.model_configuration import (
    EffectiveModel,
    ModelCreate,
    ModelKind,
    ModelPage,
    ModelProbeRead,
    ModelProbeRequest,
    ModelRead,
    ModelUpdate,
)
from app.services import model_configuration as service

router = APIRouter(prefix="/admin/models", tags=["admin-models"])
AdminDep = Annotated[User, Depends(require_permission(MODELS_MANAGE))]
SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.get("", response_model=ModelPage)
def list_models(
    admin: AdminDep,
    session: SessionDep,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    kind: ModelKind | None = None,
):
    return service.list_profiles(session, offset=offset, limit=limit, kind=kind)


@router.get("/effective", response_model=list[EffectiveModel])
def read_effective_models(admin: AdminDep, session: SessionDep, settings: SettingsDep):
    return service.effective_models(session, settings)


@router.post("", response_model=ModelRead, status_code=201)
def create_model(payload: ModelCreate, admin: AdminDep, session: SessionDep, settings: SettingsDep):
    return service.create_profile(session, admin, payload, settings)


@router.patch("/{profile_id}", response_model=ModelRead)
def update_model(
    profile_id: UUID,
    payload: ModelUpdate,
    admin: AdminDep,
    session: SessionDep,
    settings: SettingsDep,
):
    return service.update_profile(session, admin, profile_id, payload, settings)


@router.delete("/{profile_id}", status_code=204)
def delete_model(profile_id: UUID, admin: AdminDep, session: SessionDep) -> Response:
    service.delete_profile(session, admin, profile_id)
    return Response(status_code=204)


@router.post("/{profile_id}/activate", response_model=ModelRead)
def activate_model(profile_id: UUID, admin: AdminDep, session: SessionDep, settings: SettingsDep):
    return service.change_binding(session, admin, profile_id, settings, activate=True)


@router.post("/{profile_id}/test", response_model=ModelProbeRead)
async def test_model(
    profile_id: UUID,
    payload: ModelProbeRequest,
    admin: AdminDep,
    session: SessionDep,
    settings: SettingsDep,
    request: Request,
):
    from app.services.model_probes import run_probe

    return await run_probe(
        session,
        admin,
        profile_id,
        payload.expected_revision,
        settings,
        request.app.state.application_shutdown_state,
    )


@router.post("/{profile_id}/deactivate", response_model=ModelRead)
def deactivate_model(profile_id: UUID, admin: AdminDep, session: SessionDep, settings: SettingsDep):
    return service.change_binding(session, admin, profile_id, settings, activate=False)
