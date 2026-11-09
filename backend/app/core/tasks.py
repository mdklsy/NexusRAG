"""任务派发：优先 ARQ（compose 多进程架构），不可用时回退进程内执行（单机开发）。"""

import asyncio
import logging
import uuid

logger = logging.getLogger(__name__)


async def dispatch_ingest(document_id: uuid.UUID) -> str:
    """返回派发模式：arq | inline。"""
    try:
        from arq import create_pool
        from arq.connections import RedisSettings

        from app.core.config import get_settings

        pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
        try:
            await pool.enqueue_job("task_ingest_document", document_id)
            return "arq"
        finally:
            await pool.aclose()
    except Exception as e:  # noqa: BLE001  redis 不可用 → 进程内跑
        logger.warning("ARQ unavailable (%s), running ingest inline", e)
        from app.services.ingestion.pipeline import ingest_document

        asyncio.create_task(ingest_document(document_id))
        return "inline"
