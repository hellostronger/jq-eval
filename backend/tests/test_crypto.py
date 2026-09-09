# API 密钥加密存储回归测试
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import EncryptedText, decrypt_value, encrypt_value
from app.models import Model
from app.models.model_mapping import ModelMapping


def test_encrypt_decrypt_roundtrip():
    cipher = encrypt_value("sk-real-secret-key")
    assert cipher != "sk-real-secret-key"
    assert cipher.startswith("gAAAAA")
    assert decrypt_value(cipher) == "sk-real-secret-key"


def test_legacy_plaintext_passes_through():
    # 历史明文行（无 Fernet 头）原样返回，兼容渐进迁移
    assert decrypt_value("sk-old-plaintext") == "sk-old-plaintext"


@pytest.mark.asyncio
async def test_column_stores_ciphertext_returns_plaintext(db_session: AsyncSession):
    """写库透明加密：列内为密文，ORM 读回为明文"""
    model = Model(
        name="enc-test", model_type="llm", provider="openai",
        api_key_encrypted="sk-top-secret-123", status="active",
    )
    db_session.add(model)
    await db_session.commit()
    await db_session.refresh(model)

    # ORM 层：明文
    assert model.api_key_encrypted == "sk-top-secret-123"

    # 存储层：密文（绕过类型处理器直接查原始列）
    raw = (await db_session.execute(
        text("SELECT api_key_encrypted FROM models WHERE name = :n"),
        {"n": "enc-test"},
    )).scalar()
    assert raw.startswith("gAAAAA")
    assert "sk-top-secret-123" not in raw

    # 明文更新后仍是密文存储（幂等：不会二次加密密文）
    model.api_key_encrypted = decrypt_value(raw)  # 同值重写
    await db_session.commit()
    raw2 = (await db_session.execute(
        text("SELECT api_key_encrypted FROM models WHERE name = :n"),
        {"n": "enc-test"},
    )).scalar()
    assert decrypt_value(raw2) == "sk-top-secret-123"


@pytest.mark.asyncio
async def test_mapping_api_key_stored_encrypted(db_session: AsyncSession, sample_llm_model: Model):
    """对外映射服务密钥同样加密落库，proxy 鉴权读回的仍是明文"""
    mapping = ModelMapping(
        name="enc-mapping", target_model_id=sample_llm_model.id,
        api_key="sk-mx-" + "a" * 48, auth_required=True, status="active",
    )
    db_session.add(mapping)
    await db_session.commit()

    raw = (await db_session.execute(
        text("SELECT api_key FROM model_mappings WHERE name = :n"),
        {"n": "enc-mapping"},
    )).scalar()
    assert raw.startswith("gAAAAA")
    assert decrypt_value(raw) == "sk-mx-" + "a" * 48
