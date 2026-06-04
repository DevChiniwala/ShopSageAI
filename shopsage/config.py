"""
Central Configuration for ShopSage AI.

Migrated to pydantic-settings for strong validation, default values,
and type safety. Variables are loaded from the environment or .env file.
"""

import os
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    """Global configuration settings for ShopSage AI."""

    # ─── Environment ──────────────────────────────────────────────────────────
    ENVIRONMENT: str = Field(default="production", description="development, staging, or production")
    LOG_LEVEL: str = Field(default="INFO")

    # ─── API Keys ─────────────────────────────────────────────────────────────
    GOOGLE_API_KEY: str = Field(default="")
    SENTRY_DSN: str = Field(default="")

    # ─── Model Configuration ──────────────────────────────────────────────────
    LLM_MODEL: str = Field(default="gemini-2.0-flash")
    EMBEDDING_MODEL: str = Field(default="models/gemini-embedding-001")

    # ─── Paths ────────────────────────────────────────────────────────────────
    BASE_DIR: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    DATA_DIR: str = os.path.join(BASE_DIR, "data")
    DB_PATH: str = os.path.join(DATA_DIR, "shopsage.sqlite3")
    POLICY_PATH: str = os.path.join(DATA_DIR, "policy.txt")
    FAISS_INDEX_PATH: str = os.path.join(DATA_DIR, "faiss_index")

    # ─── Database & Redis ─────────────────────────────────────────────────────
    DATABASE_URL: str = Field(default="")
    REDIS_URL: str = Field(default="redis://localhost:6379/0")

    # ─── RAG Configuration ────────────────────────────────────────────────────
    CHUNK_SIZE: int = Field(default=500)
    CHUNK_OVERLAP: int = Field(default=100)
    TOP_K_RESULTS: int = Field(default=3)

    # ─── User Memory Configuration ────────────────────────────────────────────
    ENABLE_USER_MEMORY: bool = Field(default=True)
    MAX_PROFILE_NOTES_LENGTH: int = Field(default=2000)

    # ─── Scraper Configuration ────────────────────────────────────────────────
    SCRAPER_TIMEOUT: int = Field(default=8)
    SCRAPER_CACHE_TTL: int = Field(default=600)
    MAX_RESULTS_PER_STORE: int = Field(default=3)

    # ─── Server & Security Configuration ──────────────────────────────────────
    HOST: str = Field(default="0.0.0.0")
    PORT: int = Field(default=8000)
    CORS_ORIGINS: List[str] = Field(default=["http://localhost:3000", "http://localhost:8000"])
    ALLOWED_HOSTS: List[str] = Field(
        default=["localhost", "127.0.0.1"],
        description="Trusted Host header values (JSON-encoded list via ALLOWED_HOSTS env)",
    )

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Ensure data dir exists
        os.makedirs(self.DATA_DIR, exist_ok=True)
        
        # Default fallback for sqlite
        if not self.DATABASE_URL:
            # Using absolute path for sqlite is safer
            db_abs_path = os.path.abspath(self.DB_PATH).replace('\\', '/')
            self.DATABASE_URL = f"sqlite+aiosqlite:///{db_abs_path}"


# Instantiate a single global settings object
settings = Settings()
