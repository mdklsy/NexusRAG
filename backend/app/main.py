"""NexusRAG API 入口。"""

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import api_router
from app.core.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = FastAPI(
    title="NexusRAG",
    description="Open-source RAG + Knowledge Graph platform",
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

settings = get_settings()
origins = ["*"] if settings.cors_origins == "*" else settings.cors_origins.split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.on_event("startup")
async def _load_runtime_settings():
    # 启动即加载页面级全局配置（模型/向量/重排），TTL 内惰性刷新
    from app.core import runtime_settings

    await runtime_settings.refresh()


@app.get("/healthz", tags=["meta"])
async def healthz():
    return {"status": "ok", "service": "nexusrag-api"}


# 聊天挂件：app/static/widget.js，一行 <script> 嵌入即用
_static = Path(__file__).resolve().parent / "static"
if (_static / "widget.js").is_file():

    @app.get("/widget.js", include_in_schema=False)
    async def widget_js():
        from fastapi.responses import FileResponse

        return FileResponse(
            _static / "widget.js",
            media_type="application/javascript; charset=utf-8",
            headers={"Cache-Control": "public, max-age=300"},
        )


# 生产环境：若存在前端构建产物则托管（compose 中由独立 web 容器承担，此项为兜底）
if _static.is_dir():
    from fastapi.staticfiles import StaticFiles

    app.mount("/static", StaticFiles(directory=_static), name="static")
