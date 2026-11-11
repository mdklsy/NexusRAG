"""文档路由：上传 / URL 导入 / 状态查询 / 删除 / 分块查看 / 重新分块。"""

import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_role
from app.core.config import get_settings
from app.core.tasks import dispatch_ingest
from app.db.session import get_session
from app.models.kb import Chunk, Document, KnowledgeBase
from app.models.platform import User
from app.schemas import ChunkOut, DocumentOut, DocumentUrlIn
from app.services.ingestion.pipeline import purge_document, reset_document

router = APIRouter(tags=["documents"])

IN_FLIGHT_STATUSES = {"pending", "parsing", "chunking", "embedding", "extracting_kg"}
STUCK_AFTER_SECONDS = 600  # 进行中但超过 10 分钟无状态变更视为卡死，允许重新分块

ALLOWED_EXTS = {".pdf", ".docx", ".xlsx", ".md", ".txt", ".csv", ".html", ".htm", ".json"}


@router.post("/kbs/{kb_id}/documents/upload", response_model=DocumentOut, status_code=201)
async def upload_document(
    kb_id: uuid.UUID,
    file: UploadFile,
    _: User = Depends(require_role("editor")),
    session: AsyncSession = Depends(get_session),
):
    kb = await session.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(404, "知识库不存在")

    settings = get_settings()
    ext = Path(file.filename or "file.txt").suffix.lower()
    if ext and ext not in ALLOWED_EXTS:
        raise HTTPException(400, f"不支持的文件类型 {ext}，支持: {', '.join(sorted(ALLOWED_EXTS))}")

    data = await file.read()
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(400, f"文件超过 {settings.max_upload_mb}MB 限制")

    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}{ext}"
    (upload_dir / stored_name).write_bytes(data)

    doc = Document(
        kb_id=kb_id,
        name=file.filename or stored_name,
        source_type="upload",
        file_path=stored_name,
        mime_type=file.content_type,
        size_bytes=len(data),
    )
    session.add(doc)
    await session.commit()
    await session.refresh(doc)

    await dispatch_ingest(doc.id)
    return doc


@router.post("/kbs/{kb_id}/documents/url", response_model=DocumentOut, status_code=201)
async def add_url_document(
    kb_id: uuid.UUID,
    body: DocumentUrlIn,
    _: User = Depends(require_role("editor")),
    session: AsyncSession = Depends(get_session),
):
    kb = await session.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(404, "知识库不存在")
    if not body.url.startswith(("http://", "https://")):
        raise HTTPException(400, "URL 必须以 http(s):// 开头")

    doc = Document(kb_id=kb_id, name=body.url[:200], source_type="url", source_url=body.url)
    session.add(doc)
    await session.commit()
    await session.refresh(doc)

    await dispatch_ingest(doc.id)
    return doc


@router.get("/kbs/{kb_id}/documents", response_model=list[DocumentOut])
async def list_documents(
    kb_id: uuid.UUID,
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return (
        (
            await session.execute(
                select(Document)
                .where(Document.kb_id == kb_id)
                .order_by(Document.created_at.desc())
            )
        )
        .scalars()
        .all()
    )


@router.get("/documents/{document_id}", response_model=DocumentOut)
async def get_document(
    document_id: uuid.UUID,
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    doc = await session.get(Document, document_id)
    if doc is None:
        raise HTTPException(404, "文档不存在")
    return doc


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(
    document_id: uuid.UUID,
    _: User = Depends(require_role("editor")),
):
    await purge_document(document_id)


@router.post("/documents/{document_id}/reprocess", response_model=DocumentOut)
async def reprocess_document(
    document_id: uuid.UUID,
    _: User = Depends(require_role("editor")),
    session: AsyncSession = Depends(get_session),
):
    """清空已生成的分块/图谱并重新摄取。用于失败重试、恢复卡死任务（如 worker 重启中断）。"""
    doc = await session.get(Document, document_id)
    if doc is None:
        raise HTTPException(404, "文档不存在")
    if doc.status in IN_FLIGHT_STATUSES:
        updated = doc.updated_at
        age = (
            (datetime.now(timezone.utc) - updated).total_seconds()
            if updated
            else float("inf")
        )
        if age < STUCK_AFTER_SECONDS:
            raise HTTPException(
                409, "文档正在处理中，请稍后再试；若确认卡死，10 分钟后可重新分块"
            )
    await reset_document(document_id)
    await dispatch_ingest(document_id)
    await session.refresh(doc)
    return doc


@router.get("/documents/{document_id}/chunks", response_model=list[ChunkOut])
async def list_chunks(
    document_id: uuid.UUID,
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return (
        (
            await session.execute(
                select(Chunk).where(Chunk.document_id == document_id).order_by(Chunk.seq)
            )
        )
        .scalars()
        .all()
    )
