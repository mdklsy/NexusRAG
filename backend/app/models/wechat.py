"""微信公众号绑定配置。"""

import uuid

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class WechatConfig(TimestampMixin, Base):
    """一个 NexusRAG 应用绑定一个公众号（明文模式 + 签名校验）。

    回调 URL：/api/v1/wechat/{id}/callback
    """

    __tablename__ = "wechat_configs"
    __table_args__ = (UniqueConstraint("app_id", name="uq_wechat_config_app"),)

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4,
    )
    app_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("apps.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100), default="")
    wx_app_id: Mapped[str] = mapped_column(String(100), default="")  # 公众号 AppID
    verify_token: Mapped[str] = mapped_column(String(200))  # 服务器配置 Token（签名用）
    aes_key_enc: Mapped[str] = mapped_column(Text, default="")  # 预留：安全模式 EncodingAESKey
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    welcome_reply: Mapped[str] = mapped_column(Text, default="")
