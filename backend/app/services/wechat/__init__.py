"""微信公众号消息处理：签名校验 + XML 解析/构造（纯函数，便于单测）。"""

import hashlib
import re
import time
from dataclasses import dataclass
from xml.etree import ElementTree

WECHAT_TIMEOUT_REPLY = "收到，正在思考中，请稍后重新发送问题～"
MAX_REPLY_LEN = 600  # 微信文本上限 2047 字节，留足余量


@dataclass
class InboundMessage:
    from_user: str
    to_user: str
    msg_type: str
    content: str


def check_signature(token: str, signature: str, timestamp: str, nonce: str) -> bool:
    """微信服务器 GET 校验：sha1(sort(token, timestamp, nonce)) == signature。"""
    raw = "".join(sorted([token, timestamp, nonce]))
    return hashlib.sha1(raw.encode()).hexdigest() == signature


def parse_inbound(xml_text: str) -> InboundMessage | None:
    """解析微信推送的 XML（明文模式）。仅关心 text 消息，其余返回带类型供忽略。"""
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return None
    to_user = root.findtext("ToUserName") or ""
    from_user = root.findtext("FromUserName") or ""
    msg_type = root.findtext("MsgType") or ""
    content = root.findtext("Content") or ""
    return InboundMessage(
        from_user=from_user, to_user=to_user, msg_type=msg_type, content=content.strip()
    )


def _xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def build_text_reply(from_user: str, to_user: str, content: str) -> str:
    """构造被动回复 XML（注意：ToUserName 是粉丝 openid）。"""
    content = content.strip()[:MAX_REPLY_LEN]
    return (
        "<xml>"
        f"<ToUserName><![CDATA[{to_user}]]></ToUserName>"
        f"<FromUserName><![CDATA[{from_user}]]></FromUserName>"
        f"<CreateTime>{int(time.time())}</CreateTime>"
        "<MsgType><![CDATA[text]]></MsgType>"
        f"<Content><![CDATA[{content}]]></Content>"
        "</xml>"
    )


def strip_markdown(text: str) -> str:
    """公众号纯文本场景：去掉常见 markdown 标记。"""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", text)  # 链接只留文字
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"[*_`>]+", "", text)
    return text
