"""Application Configuration Module using Pydantic Settings."""

import os
from pathlib import Path
from typing import List, Union
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Core settings for ORIGIN AI execution engine and API."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Project metadata
    PROJECT_NAME: str = "ORIGIN AI"
    VERSION: str = "0.1.0"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    API_V1_STR: str = "/api/v1"

    # Database
    DATABASE_URL: str = "sqlite:///./origin_ai.db"

    # Storage & Workspace Isolation
    WORKSPACE_DIR: Path = Path("./workspace").resolve()
    MAX_FILE_SIZE_MB: int = 50
    ALLOWED_FILE_EXTENSIONS: List[str] = [
        ".pdf",
        ".docx",
        ".txt",
        ".xlsx",
        ".csv",
        ".json",
        ".md",
    ]

    # LLM Settings
    DEFAULT_LLM_PROVIDER: str = "groq"
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "openai/gpt-oss-120b"

    # Execution Engine Settings
    EXECUTION_TIMEOUT_SECONDS: int = 180
    MAX_STEP_RETRIES: int = 2

    # CORS
    CORS_ORIGINS: Union[List[str], str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",") if i.strip()]
        elif isinstance(v, str) and v.startswith("["):
            import json

            try:
                return json.loads(v)
            except Exception:
                return ["*"]
        return v

    @field_validator("WORKSPACE_DIR", mode="after")
    @classmethod
    def ensure_workspace_dir(cls, v: Path) -> Path:
        resolved = v.resolve()
        resolved.mkdir(parents=True, exist_ok=True)
        return resolved


settings = Settings()
