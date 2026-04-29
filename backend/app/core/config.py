# 应用配置
from pydantic_settings import BaseSettings
from typing import Optional
from functools import lru_cache


class Settings(BaseSettings):
    """应用配置"""

    # 应用基础配置
    APP_NAME: str = "JQ-Eval"
    APP_VERSION: str = "1.0.0"
    APP_ENV: str = "development"
    APP_DEBUG: bool = True
    SECRET_KEY: str = "your-secret-key-change-in-production"

    # 数据库配置
    POSTGRES_HOST: str = "101.43.25.101"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "jqeval"
    POSTGRES_USER: str = "jqeval"
    POSTGRES_PASSWORD: str = "jqeval123"

    @property
    def DATABASE_URL(self) -> str:
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    @property
    def DATABASE_URL_SYNC(self) -> str:
        return f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    # Redis配置
    REDIS_HOST: str = "101.43.25.101"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = "jqeval123"
    REDIS_DB: int = 0

    @property
    def REDIS_URL(self) -> str:
        return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    # MinIO配置
    MINIO_HOST: str = "101.43.25.101"
    MINIO_PORT: int = 9000
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin123"
    MINIO_BUCKET: str = "jqeval"
    MINIO_SECURE: bool = False

    # Milvus配置
    MILVUS_HOST: str = "101.43.25.101"
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
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    """获取配置单例"""
    return Settings()


settings = get_settings()