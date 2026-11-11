"""运行时全局配置：模型/向量/重排服务的页面级配置（DB 覆盖 .env）。

设计：
- system_settings 表按类别（llm / embedding / rerank）存 JSON，
  api_key 用 AES 加密落库（复用 core.crypto）。
- 进程内 CACHE + TTL 惰性刷新（ensure_fresh，异步上下文调用）；
  保存配置后 refresh() 立即生效，无需重启容器。
- 同步 getter（get_global_llm 等）读缓存，缺省回退 .env——
  保持 get_llm_client / get_embedding_client 的同步签名不变。
"""

import time
from typing import Any

from app.core.config import get_settings
from app.db.session import session_scope

CATEGORIES = ("llm", "embedding", "rerank")
_TTL = 30  # 秒

_cache: dict[str, dict] = {}
_loaded_at: float = 0.0


def _env_fallback(category: str) -> dict:
    """该类别的 .env 兜底值（api_key 明文，仅供进程内构造客户端）。"""
    s = get_settings()
    if category == "llm":
        return {
            "api_base": s.effective_llm_base,
            "api_key": s.effective_llm_key,
            "model": s.llm_model,
        }
    if category == "embedding":
        return {
            "api_base": s.effective_embedding_base,
            "api_key": s.effective_embedding_key,
            "model": s.embedding_model,
        }
    return {
        "api_base": s.rerank_api_base,
        "api_key": s.rerank_api_key,
        "model": s.rerank_model,
    }


async def refresh() -> None:
    """从 DB 全量加载三类配置到缓存（解密 api_key）。"""
    global _cache, _loaded_at
    from sqlalchemy import select

    from app.core.crypto import decrypt_secret
    from app.models.platform import SystemSetting

    merged: dict[str, dict] = {}
    try:
        async with session_scope() as session:
            rows = (
                (await session.execute(select(SystemSetting))).scalars().all()
            )
        for row in rows:
            if row.skey not in CATEGORIES:
                continue
            data: dict[str, Any] = dict(row.value or {})
            enc = data.pop("api_key_enc", "")
            if enc:
                try:
                    data["api_key"] = decrypt_secret(enc)
                except Exception:  # noqa: BLE001 解密失败视为未设置
                    data["api_key"] = ""
            merged[row.skey] = data
    except Exception:  # noqa: BLE001 表不存在（旧库未迁移）等，回退 env
        merged = {}
    _cache = merged
    _loaded_at = time.monotonic()


async def ensure_fresh() -> None:
    """TTL 过期则刷新；异步入口在构建客户端前调用。"""
    if time.monotonic() - _loaded_at > _TTL:
        await refresh()


def invalidate() -> None:
    """保存配置后调用：清缓存，下次 ensure_fresh 必刷。"""
    global _loaded_at
    _loaded_at = 0.0


def get_global(category: str) -> dict:
    """同步读取某类别生效配置（DB 覆盖 .env）。api_key 为明文。"""
    base = _env_fallback(category)
    override = _cache.get(category) or {}
    return {
        "api_base": override.get("api_base") or base["api_base"],
        "api_key": override.get("api_key") if override.get("api_key") else base["api_key"],
        "model": override.get("model") or base["model"],
    }


async def save_category(category: str, data: dict) -> None:
    """写/更新某类别配置。api_key 非空才覆盖（空 = 保持不变）。"""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.core.crypto import encrypt_secret
    from app.models.platform import SystemSetting

    if category not in CATEGORIES:
        raise ValueError(f"未知配置类别 {category}")
    value: dict[str, Any] = {}
    if data.get("api_base"):
        value["api_base"] = data["api_base"].strip()
    if data.get("model"):
        value["model"] = data["model"].strip()
    if data.get("api_key"):
        value["api_key_enc"] = encrypt_secret(data["api_key"])
    # 保留原有未提交字段（尤其已存的 api_key_enc）
    async with session_scope() as session:
        stmt = (
            pg_insert(SystemSetting)
            .values(skey=category, value=value)
            .on_conflict_do_update(
                index_elements=["skey"],
                set_={"value": value},
            )
        )
        # 旧库无该表时报错上抛（需先跑迁移 0006）
        await session.execute(stmt)
        await session.commit()
    await refresh()


def masked_status(category: str) -> dict:
    """API 输出：生效值 + 掩码后的 key 状态（不泄露明文）。"""
    from app.core.crypto import mask_secret

    eff = get_global(category)
    override = _cache.get(category) or {}
    key_plain = eff.get("api_key") or ""
    return {
        "api_base": eff["api_base"],
        "model": eff["model"],
        "api_key_set": bool(key_plain),
        "api_key_masked": mask_secret(key_plain) if key_plain else "",
        "from_db": bool(override),
    }
