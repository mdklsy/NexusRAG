"""API v1 路由汇总。"""

from fastapi import APIRouter

from app.api.v1 import (
    approvals,
    apps,
    auth,
    chat,
    dashboard,
    documents,
    evals,
    kbs,
    settings,
    retrievals,
    tools,
    users,
    wechat,
    widget,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(settings.router)
api_router.include_router(kbs.router)
api_router.include_router(documents.router)
api_router.include_router(apps.router)
api_router.include_router(approvals.router)
api_router.include_router(tools.router)
api_router.include_router(users.router)
api_router.include_router(widget.router)
api_router.include_router(retrievals.router)
api_router.include_router(chat.router)
api_router.include_router(evals.router)
api_router.include_router(wechat.router)
api_router.include_router(dashboard.router)
