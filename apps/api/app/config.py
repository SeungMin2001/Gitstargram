from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://gitstargram:gitstargram@localhost:5432/gitstargram"
    redis_url: str = "redis://localhost:6379/0"
    frontend_url: str = "http://localhost:3000"
    backend_url: str = "http://localhost:8000"
    github_client_id: str = ""
    github_client_secret: str = ""
    github_api_version: str = "2026-03-10"
    session_secret: str = ""
    cookie_secure: bool = False
    ai_base_url: str = "http://localhost:8001/v1"
    ai_model_name: str = "Qwen/Qwen3.5-4B"
    embedding_base_url: str = "http://localhost:8002/v1"
    embedding_model_name: str = "Qwen/Qwen3-Embedding-0.6B"
    embedding_dimensions: int = 1024
    aws_region: str = "ap-northeast-2"
    aws_s3_bucket: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def settings() -> Settings:
    return Settings()

