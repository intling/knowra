from fastapi import APIRouter

from app.api.routes import document_parsing, health, uploads, users

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(uploads.router)
api_router.include_router(document_parsing.router)
api_router.include_router(users.router)
