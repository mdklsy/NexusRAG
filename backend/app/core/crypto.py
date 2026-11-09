"""敏感凭证加密（AES-GCM，密钥由 SECRET_KEY 派生）。

用途：应用级 LLM api_key 等敏感配置的库内加密存储。
"""

import base64
import hashlib

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings


def _derive_key() -> bytes:
    return hashlib.sha256(("nexusrag:" + get_settings().secret_key).encode()).digest()


def encrypt_secret(plain: str) -> str:
    """加密为 base64(nonce + ciphertext)。空串原样返回。"""
    if not plain:
        return ""
    import os

    nonce = os.urandom(12)
    ct = AESGCM(_derive_key()).encrypt(nonce, plain.encode(), b"nexusrag")
    return base64.b64encode(nonce + ct).decode()


def decrypt_secret(token: str) -> str:
    if not token:
        return ""
    raw = base64.b64decode(token)
    plain = AESGCM(_derive_key()).decrypt(raw[:12], raw[12:], b"nexusrag")
    return plain.decode()


def mask_secret(plain_or_cipher: str, *, encrypted: bool = False) -> str:
    """打码展示：sk-abcd1234... → sk-****1234。无法解密时返回 '****'。"""
    try:
        plain = decrypt_secret(plain_or_cipher) if encrypted else plain_or_cipher
    except Exception:  # noqa: BLE001
        return "****"
    if not plain:
        return ""
    tail = plain[-4:] if len(plain) > 8 else ""
    return f"{plain[:3]}****{tail}" if tail else "****"
