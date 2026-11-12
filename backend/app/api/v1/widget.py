"""网页挂件路由：前端一行 script 嵌入所需的公开配置。"""

from fastapi import APIRouter, Depends

from app.api.deps import get_app_by_api_key
from app.models.app import App
from app.schemas import WidgetConfigOut

router = APIRouter(prefix="/widget", tags=["widget"])


@router.get("/config", response_model=WidgetConfigOut)
async def widget_config(app: App = Depends(get_app_by_api_key)):
    """挂件初始化配置（API Key 认证；建议为挂件单独发 scope=chat 的 Key）。"""
    cfg = app.widget_config or {}
    return WidgetConfigOut(
        app_id=app.id,
        title=cfg.get("title") or app.name,
        welcome=cfg.get("welcome") or f"你好，我是{app.name}，请问有什么可以帮你？",
        theme=cfg.get("theme") or "#1677ff",
        bubble=cfg.get("bubble") or "💬",
        app_name=app.name,
    )
