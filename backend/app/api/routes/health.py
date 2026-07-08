from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.core.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["health"])
SettingsDep = Annotated[Settings, Depends(get_settings)]


class HealthResponse(BaseModel):
    status: str
    app_name: str
    environment: str
    document_models: dict | None = None


@router.get("/health", response_model=HealthResponse)
def read_health(request: Request, settings: SettingsDep) -> HealthResponse:
    logger.debug("健康检查", app_name=settings.app_name, environment=settings.app_env)
    return HealthResponse(
        status="ok",
        app_name=settings.app_name,
        environment=settings.app_env,
        document_models=serialize_document_model_readiness(
            getattr(request.app.state, "document_model_readiness", None),
            shutdown_state=getattr(request.app.state, "application_shutdown_state", None),
        ),
    )


def serialize_document_model_readiness(
    readiness: object | None,
    *,
    shutdown_state: object | None = None,
) -> dict:
    if getattr(shutdown_state, "is_shutting_down", False):
        return {
            "status": "shutting_down",
            "docling": serialize_component_as_shutting_down(getattr(readiness, "docling", None)),
            "tokenizer": serialize_component_as_shutting_down(
                getattr(readiness, "tokenizer", None)
            ),
        }
    if readiness is None:
        return {"status": "skipped", "docling": None, "tokenizer": None}

    return {
        "status": getattr(readiness, "status", "skipped"),
        "docling": serialize_component(getattr(readiness, "docling", None)),
        "tokenizer": serialize_component(getattr(readiness, "tokenizer", None)),
    }


def serialize_component_as_shutting_down(component: object | None) -> dict | None:
    if component is None:
        return None
    return {
        "status": "shutting_down",
        "missing_models": list(getattr(component, "missing_models", []) or []),
    }


def serialize_component(component: object | None) -> dict | None:
    if component is None:
        return None
    return {
        "status": getattr(component, "status", "skipped"),
        "missing_models": list(getattr(component, "missing_models", []) or []),
    }
