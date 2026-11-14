"""ACL v2 规则引擎：属性声明（claims）+ 终端用户 ID 白名单，块级覆盖文档级。

规则形状（documents.acl 与 chunks.acl 统一）：
    {"mode": "public"}                                          # 所有人可见
    {"mode": "restricted",
     "end_users": ["op1"],                                      # ID 白名单（兼容保留）
     "claims": [{"key": "dept", "values": ["销售部", "vip"]}]}   # 属性声明条件

授权 = end_users 命中 或 claims 全部条件满足（多条件 AND、条件内多值 OR；
用户属性缺失视为不满足；属性值统一转 str 比较，数组属性任一元素命中即可）。

块级覆盖模式：chunk.acl 有值时该块可见性完全由块规则决定，与文档规则无关；
chunk.acl 为 NULL 则继承文档规则。
"""

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.kb import Chunk, Document


def eval_rules(rules: dict | None, end_user_id: str | None, attributes: dict | None) -> bool:
    """判断单个规则对象是否授权该终端用户。None/无 mode 视为公开。"""
    if not rules or rules.get("mode") != "restricted":
        return True
    # ID 白名单
    if end_user_id and end_user_id in (rules.get("end_users") or []):
        return True
    # 属性声明：全部条件满足
    claims = rules.get("claims") or []
    if claims:
        attrs = attributes or {}
        for cond in claims:
            key = str((cond or {}).get("key") or "").strip()
            values = [str(v) for v in ((cond or {}).get("values") or []) if str(v).strip()]
            if not key or not values:
                return False  # 条件本身配置不完整 → 不授权
            user_val = attrs.get(key)
            if user_val is None:
                return False  # 缺失声明 → 不满足
            user_vals = user_val if isinstance(user_val, (list, tuple, set)) else [user_val]
            if not any(str(v) in values for v in user_vals):
                return False
        return True
    return False  # restricted 但既无 end_users 也无 claims → 无人可见（配置错误兜底）


@dataclass
class AclFilter:
    """检索过滤判定：命中任一 deny 集则丢弃该候选块。"""

    deny_doc_ids: set[uuid.UUID] = field(default_factory=set)
    deny_chunk_ids: set[uuid.UUID] = field(default_factory=set)

    def allows(self, chunk_id: uuid.UUID, document_id: uuid.UUID) -> bool:
        return document_id not in self.deny_doc_ids and chunk_id not in self.deny_chunk_ids


async def resolve_acl(
    session: AsyncSession, kb_ids: list[uuid.UUID], end_user: dict | None
) -> AclFilter | None:
    """按终端用户（含属性声明）计算检索过滤集。

    返回 None = 无需过滤：调用方无终端身份（控制台/评测/开放服务端直连视为
    运营侧全量可见），或 KB 内没有任何受限规则。
    """
    if not kb_ids:
        return None
    user_id = (end_user or {}).get("id")
    if not user_id:
        return None
    attributes = (end_user or {}).get("attributes") or {}

    docs = (
        (
            await session.execute(
                select(Document).where(
                    Document.kb_id.in_(kb_ids), Document.status == "completed"
                )
            )
        )
        .scalars()
        .all()
    )
    denied_docs = [d for d in docs if not eval_rules(d.acl, user_id, attributes)]
    allowed_doc_ids = [d.id for d in docs if d.id not in {x.id for x in denied_docs}]
    if not denied_docs:
        # 全部文档授权 → 只需检查块级覆盖（授权文档里可以封块）
        chunks = (
            (
                await session.execute(
                    select(Chunk).where(
                        Chunk.document_id.in_(allowed_doc_ids), Chunk.acl.is_not(None)
                    )
                )
            )
            .scalars()
            .all()
        )
        deny_chunks = {c.id for c in chunks if not eval_rules(c.acl, user_id, attributes)}
        if not deny_chunks:
            return None
        return AclFilter(deny_chunk_ids=deny_chunks)

    flt = AclFilter(deny_doc_ids={d.id for d in denied_docs})
    # 拉取与权限相关的块：未授权文档的全部块（找块级例外放行）+ 授权文档里设了块规则的块
    from sqlalchemy import or_

    chunks = (
        (
            await session.execute(
                select(Chunk).where(
                    or_(
                        Chunk.document_id.in_([d.id for d in denied_docs]),
                        Chunk.document_id.in_(allowed_doc_ids) & Chunk.acl.is_not(None),
                    )
                )
            )
        )
        .scalars()
        .all()
    )
    for c in chunks:
        if c.acl is None:
            continue  # 继承文档规则（未授权文档 → 随文档被 deny_doc_ids 拦截）
        granted = eval_rules(c.acl, user_id, attributes)
        if c.document_id in flt.deny_doc_ids:
            if granted:
                continue  # 块级例外：受限文档里显式放行的块（public 或 claims 命中）
            flt.deny_chunk_ids.add(c.id)  # 双保险：未授权文档内未例外的块逐块拒绝
        elif not granted:
            flt.deny_chunk_ids.add(c.id)  # 授权文档里的块级封锁
    return flt
