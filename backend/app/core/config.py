# 应用配置
from pathlib import Path

from pydantic_settings import BaseSettings
from functools import lru_cache

# 项目根目录（backend/app/core/config.py -> 上溯 4 级）；
# env_file 必须绝对化：uvicorn 从 backend/ 启动而 README 把 .env 放项目根，
# 相对路径会静默不加载，所有默认值直接生效
_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """应用配置"""

    # 应用基础配置
    APP_NAME: str = "JQ-Eval"
    APP_VERSION: str = "1.0.0"
    APP_ENV: str = "development"
    APP_DEBUG: bool = True
    SECRET_KEY: str = "your-secret-key-change-in-production"
    # API 密钥静态加密主密钥（Fernet）；留空则从 SECRET_KEY 派生。
    # 生产部署务必设置独立值——SECRET_KEY 默认占位符派生的密钥可被任何读源码者重建
    FIELD_ENCRYPTION_KEY: str = ""
    # CORS 允许来源（逗号分隔），"*" 仅用于开发
    ALLOWED_ORIGINS: str = "*"

    # 数据库配置（默认 localhost，配合 docker-compose 本地开发；
    # 生产通过根目录 .env 覆盖，切勿把真实服务器地址写进代码默认值）
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "jqeval"
    POSTGRES_USER: str = "jqeval"
    POSTGRES_PASSWORD: str = "jqeval123"

    @property
    def DATABASE_URL(self) -> str:
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    # Redis配置
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = "jqeval123"
    REDIS_DB: int = 0

    @property
    def REDIS_URL(self) -> str:
        return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    # MinIO配置
    MINIO_HOST: str = "localhost"
    MINIO_PORT: int = 9000
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin123"
    MINIO_BUCKET: str = "jqeval"
    MINIO_SECURE: bool = False

    # Milvus配置
    MILVUS_HOST: str = "localhost"
    MILVUS_PORT: int = 19530
    MILVUS_COLLECTION_PREFIX: str = "jqeval"

    # JWT配置
    JWT_SECRET_KEY: str = "your-jwt-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 1440  # 24小时

    # Celery配置
    @property
    def CELERY_BROKER_URL(self) -> str:
        return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/1"

    @property
    def CELERY_RESULT_BACKEND(self) -> str:
        return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/1"

    # VibeAgent 配置
    SANDBOX_URL: str = ""  # 沙箱服务地址，空则使用本地子进程
    SANDBOX_TIMEOUT: int = 60  # 执行超时（秒）
    SANDBOX_MAX_MEMORY: int = 256  # 最大内存（MB）

    # VibeAgent LLM 配置（用于槽位生成和代码生成）
    VIBEAGENT_LLM_URL: str = "https://api.openai.com/v1"
    VIBEAGENT_LLM_KEY: str = ""
    VIBEAGENT_LLM_MODEL: str = "gpt-4o-mini"
    VIBEAGENT_LLM_TEMPERATURE: float = 0.7
    VIBEAGENT_LLM_MAX_TOKENS: int = 4000

    class Config:
        env_file = str(_ROOT / ".env")
        env_file_encoding = "utf-8"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    """获取配置单例"""
    return Settings()


settings = get_settings()