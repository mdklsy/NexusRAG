"""数据看板路由。"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import Integer, cast, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_session
from app.models.app import App, UsageEvent
from app.models.kb import Chunk, Document, Entity, KnowledgeBase, Relation
from app.models.platform import User
from app.schemas import DashboardOverview, TimeseriesPoint

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _since(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


@router.get("/overview", response_model=DashboardOverview)
async def overview(
    days: int = 30,
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    since = _since(days)
    stats = (
        await session.execute(
            select(
                func.count(),
                func.coalesce(func.sum(UsageEvent.tokens_in), 0),
                func.coalesce(func.sum(UsageEvent.tokens_out), 0),
                func.coalesce(func.avg(UsageEvent.latency_ms), 0),
            ).where(UsageEvent.created_at >= since, UsageEvent.type == "chat")
        )
    ).one()
    hits = (
        await session.execute(
            select(
                func.count(),
                func.coalesce(func.sum(cast(UsageEvent.hit, Integer)), 0),
            ).where(UsageEvent.created_at >= since, UsageEvent.type == "chat")
        )
    ).one()
    total_chats, hit_count = int(hits[0] or 0), int(hits[1] or 0)
    cached = (
        await session.execute(
            select(
                func.count(),
                func.coalesce(func.sum(UsageEvent.tokens_in + UsageEvent.tokens_out), 0),
            ).where(UsageEvent.created_at >= since, UsageEvent.type == "chat", UsageEvent.cached.is_(True))
        )
    ).one()

    async def count(model, *conds) -> int:
        return int(
            await session.scalar(select(func.count()).select_from(model).where(*conds)) or 0
        )

    hit_rate = (hit_count / total_chats) if total_chats else 0.0
    return DashboardOverview(
        total_chats=total_chats,
        total_tokens_in=int(stats[1] or 0),
        total_tokens_out=int(stats[2] or 0),
        avg_latency_ms=int(stats[3] or 0),
        hit_rate=round(hit_rate, 4),
        total_documents=await count(Document),
        total_chunks=await count(Chunk),
        total_entities=await count(Entity),
        total_relations=await count(Relation),
        total_apps=await count(App),
        total_kbs=await count(KnowledgeBase),
        cached_chats=int(cached[0] or 0),
        cached_tokens=int(cached[1] or 0),
    )


@router.get("/timeseries", response_model=list[TimeseriesPoint])
async def timeseries(
    days: int = 30,
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    since = _since(days)
    # GROUP BY 1：asyncpg 会把 'day' 参数化，SELECT/GROUP BY 里的
    # date_trunc 表达式因占位符序号不同文本不等价，PG 判定未分组（SQLite 宽松测不出）
    rows = (
        await session.execute(
            select(
                func.to_char(func.date_trunc("day", UsageEvent.created_at), "YYYY-MM-DD"),
                func.count(),
                func.coalesce(
                    func.sum(UsageEvent.tokens_in + UsageEvent.tokens_out), 0
                ),
            )
            .where(UsageEvent.created_at >= since, UsageEvent.type == "chat")
            .group_by(text("1"))
            .order_by(text("1"))
        )
    ).all()
    return [TimeseriesPoint(date=r[0], chats=int(r[1]), tokens=int(r[2] or 0)) for r in rows]
