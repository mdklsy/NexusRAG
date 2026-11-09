"""ARQ worker：异步执行摄取任务（compose 架构下与 API 分进程）。"""

import logging
import uuid

from arq.connections import RedisSettings

from app.core.config import get_settings
from app.services.ingestion.pipeline import ingest_document

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


async def task_ingest_document(ctx, document_id: str) -> None:
    logger.info("ingest start: %s", document_id)
    await ingest_document(uuid.UUID(document_id))
    logger.info("ingest done: %s", document_id)


class WorkerSettings:
    functions = [task_ingest_document]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_jobs = 4
    job_timeout = 1800  # 大文档 KG 抽取可能较慢


if __name__ == "__main__":
    from arq import run_worker

    run_worker(WorkerSettings)
