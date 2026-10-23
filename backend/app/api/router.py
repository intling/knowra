from fastapi import APIRouter, Depends

from app.api.deps import get_current_user, verify_trusted_origin
from app.api.routes import (
    admin_models,
    admin_operations,
    admin_users,
    auth,
    document_chunking,
    document_embedding,
    document_parsing,
    health,
    pipeline_verification,
    search,
    uploads,
    users,
)

api_router = APIRouter(dependencies=[Depends(verify_trusted_origin)])
api_router.include_router(health.router)
api_router.include_router(auth.router)
for private_router in (
    admin_models.router,
    admin_operations.router,
    uploads.router,
    document_parsing.router,
    document_chunking.router,
    document_embedding.router,
    pipeline_verification.router,
    users.router,
    search.router,
    admin_users.router,
):
    api_router.include_router(private_router, dependencies=[Depends(get_current_user)])
