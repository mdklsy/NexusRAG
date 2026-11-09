"""API v1 路由汇总。"""

from fastapi import APIRouter

from app.api.v1 import apps, auth, chat, dashboard, documents, kbs, retrievals

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(kbs.router)
api_router.include_router(documents.router)
api_router.include_router(apps.router)
api_router.include_router(retrievals.router)
api_router.include_router(chat.router)
api_router.include_router(dashboard.router)
