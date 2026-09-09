# 静态数据加密（API 密钥等敏感字段）
#
# Model.api_key_encrypted 列通过 EncryptedText 类型在写库时 Fernet 加密、
# 读库时自动解密；对上层代码完全透明。历史明文行解密失败时原样返回，
# 下次更新自动转加密——渐进迁移无需数据脚本。
import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

from .config import settings

logger = logging.getLogger(__name__)

_FERNET_PREFIX = "gAAAAA"  # Fernet token 固定头部（version 0x80 + timestamp 编码）


def _load_fernet() -> Fernet:
    key = settings.FIELD_ENCRYPTION_KEY
    if not key:
        if settings.SECRET_KEY == "your-secret-key-change-in-production":
            logger.warning(
                "FIELD_ENCRYPTION_KEY 未配置且 SECRET_KEY 为默认占位值，"
                "API 密钥加密仅具形式意义；生产环境请在 .env 设置独立密钥"
            )
        # SECRET_KEY 派生：SHA-256 摘要转 base64 作为 32 字节 Fernet key
        digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
        key = base64.urlsafe_b64encode(digest).decode("ascii")
    return Fernet(key.encode("ascii") if isinstance(key, str) else key)


_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = _load_fernet()
    return _fernet


def encrypt_value(plain: str) -> str:
    """加密明文；空值原样返回"""
    if not plain:
        return plain
    return _get_fernet().encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt_value(stored: str) -> str:
    """解密存储值；非 Fernet 格式（历史明文）原样返回"""
    if not stored or not stored.startswith(_FERNET_PREFIX):
        return stored
    try:
        return _get_fernet().decrypt(stored.encode("ascii")).decode("utf-8")
    except InvalidToken:
        # 密钥更换导致旧密文不可解——返回空而非密文，避免错误凭据被透传给上游
        logger.error("API 密钥解密失败（FIELD_ENCRYPTION_KEY 是否变更？），需在模型配置页重新录入")
        return ""


class EncryptedText(TypeDecorator):
    """透明加密文本列：写库自动加密、读库自动解密。

    历史明文行（无 Fernet 前缀）读时原样返回，下次更新自动转为加密——
    渐进迁移无需数据脚本。上层代码（掩码展示/出站请求头/LangChain 构造）
    拿到的始终是明文，杜绝"忘了 decrypt"把密文当密钥发给上游的整类 bug。
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, str) and value.startswith(_FERNET_PREFIX):
            return value  # 已是密文，避免二次加密
        return encrypt_value(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return decrypt_value(value)

