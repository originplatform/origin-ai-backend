"""Application Configuration Module using Pydantic Settings."""

import os
from pathlib import Path
from typing import List, Union
from urllib.parse import urlparse
from pydantic import field_validator, model_validator
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

    # Authentication
    JWT_SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    JWT_ISSUER: str = "origin-ai"
    JWT_AUDIENCE: str = "origin-ai-client"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/api/v1/auth/google/callback"
    FRONTEND_URL: str = "http://localhost:5173"
    COOKIE_SECURE: bool = False
    COOKIE_SAMESITE: str = "lax"
    AUTH_LOGIN_RATE_LIMIT: str = "5/minute"
    AUTH_REGISTER_RATE_LIMIT: str = "5/hour"

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
            except json.JSONDecodeError as exc:
                raise ValueError("CORS_ORIGINS must be a comma-separated list or valid JSON.") from exc
        return v

    @field_validator("WORKSPACE_DIR", mode="after")
    @classmethod
    def ensure_workspace_dir(cls, v: Path) -> Path:
        resolved = v.resolve()
        resolved.mkdir(parents=True, exist_ok=True)
        return resolved

    @field_validator("JWT_ALGORITHM")
    @classmethod
    def validate_jwt_algorithm(cls, value: str) -> str:
        allowed_algorithms = {"HS256", "HS384", "HS512"}
        if value not in allowed_algorithms:
            raise ValueError("JWT_ALGORITHM must be one of HS256, HS384, or HS512.")
        return value

    @field_validator("ACCESS_TOKEN_EXPIRE_MINUTES")
    @classmethod
    def validate_access_token_lifetime(cls, value: int) -> int:
        if not 1 <= value <= 60:
            raise ValueError("ACCESS_TOKEN_EXPIRE_MINUTES must be between 1 and 60.")
        return value

    @field_validator("REFRESH_TOKEN_EXPIRE_DAYS")
    @classmethod
    def validate_refresh_token_lifetime(cls, value: int) -> int:
        if not 1 <= value <= 90:
            raise ValueError("REFRESH_TOKEN_EXPIRE_DAYS must be between 1 and 90.")
        return value

    @field_validator("COOKIE_SAMESITE")
    @classmethod
    def validate_cookie_samesite(cls, value: str) -> str:
        normalized = value.casefold()
        if normalized not in {"lax", "strict", "none"}:
            raise ValueError("COOKIE_SAMESITE must be lax, strict, or none.")
        return normalized

    @field_validator("FRONTEND_URL", "GOOGLE_REDIRECT_URI")
    @classmethod
    def validate_auth_urls(cls, value: str) -> str:
        parsed = urlparse(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username
            or parsed.password
        ):
            raise ValueError("Authentication URLs must be valid HTTP(S) URLs.")
        return value

    @field_validator("CORS_ORIGINS")
    @classmethod
    def validate_credentialed_cors_origins(cls, value: Union[List[str], str]):
        origins = value if isinstance(value, list) else [value]
        if "*" in origins:
            raise ValueError(
                "Wildcard CORS origins are not allowed with credentialed requests."
            )
        for origin in origins:
            parsed = urlparse(origin)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.username
                or parsed.password
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("Each CORS origin must be a valid HTTP(S) origin.")
        return origins

    @model_validator(mode="after")
    def validate_production_auth_settings(self):
        secret_bytes = self.JWT_SECRET_KEY.encode("utf-8")
        minimum_secret_length = {
            "HS256": 32,
            "HS384": 48,
            "HS512": 64,
        }[self.JWT_ALGORITHM]
        is_production = self.ENVIRONMENT.casefold() in {"production", "prod"}

        if bool(self.GOOGLE_CLIENT_ID) != bool(self.GOOGLE_CLIENT_SECRET):
            raise ValueError(
                "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be configured together."
            )
        if self.JWT_SECRET_KEY and len(secret_bytes) < minimum_secret_length:
            raise ValueError(
                f"JWT_SECRET_KEY must contain at least {minimum_secret_length} bytes "
                f"for {self.JWT_ALGORITHM}."
            )
        if self.COOKIE_SAMESITE == "none" and not self.COOKIE_SECURE:
            raise ValueError("COOKIE_SECURE must be true when COOKIE_SAMESITE is none.")
        if is_production:
            if len(secret_bytes) < minimum_secret_length:
                raise ValueError(
                    "Production requires a strong JWT_SECRET_KEY configured through "
                    "the environment."
                )
            if not self.COOKIE_SECURE:
                raise ValueError("Production requires COOKIE_SECURE=true.")
            if (
                urlparse(self.FRONTEND_URL).scheme != "https"
                or urlparse(self.GOOGLE_REDIRECT_URI).scheme != "https"
            ):
                raise ValueError("Production authentication URLs must use HTTPS.")
            if any(urlparse(origin).scheme != "https" for origin in self.CORS_ORIGINS):
                raise ValueError("Production CORS origins must use HTTPS.")
        return self


settings = Settings()
