"""任务派发：优先 ARQ（compose 多进程架构），不可用时回退进程内执行（单机开发）。"""

import asyncio
import logging
import uuid

logger = logging.getLogger(__name__)

ARQ_CONNECT_TIMEOUT = 3  # Redis 缺席时避免长时间阻塞用户请求


async def _enqueue(function: str, *args) -> None:
    from arq import create_pool
    from arq.connections import RedisSettings

    from app.core.config import get_settings

    pool = await asyncio.wait_for(
        create_pool(
            RedisSettings.from_dsn(get_settings().redis_url),
            connect_timeout=ARQ_CONNECT_TIMEOUT,
        ),
        timeout=ARQ_CONNECT_TIMEOUT + 2,
    )
    try:
        await pool.enqueue_job(function, *args)
    finally:
        await pool.aclose()


async def dispatch_ingest(document_id: uuid.UUID) -> str:
    """返回派发模式：arq | inline。"""
    try:
        await _enqueue("task_ingest_document", document_id)
        return "arq"
    except Exception as e:  # noqa: BLE001  redis 不可用 → 进程内跑
        logger.warning("ARQ unavailable (%s), running ingest inline", e)
        from app.services.ingestion.pipeline import ingest_document

        asyncio.create_task(ingest_document(document_id))
        return "inline"


async def dispatch_eval(run_id: uuid.UUID) -> str:
    """评测运行派发，同上策略。"""
    try:
        await _enqueue("task_run_eval", run_id)
        return "arq"
    except Exception as e:  # noqa: BLE001
        logger.warning("ARQ unavailable (%s), running eval inline", e)
        from app.services.evaluator import run_eval

        asyncio.create_task(run_eval(run_id))
        return "inline"
