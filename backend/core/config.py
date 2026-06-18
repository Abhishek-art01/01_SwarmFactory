"""
core/config.py
--------------
Central configuration loader for Swarm Factory backend.
Reads all required environment variables from a .env file using Pydantic Settings.
Any missing required variable will raise a clear error at startup — fail fast, fail loud.

Usage:
    from core.config import settings
    print(settings.REDIS_URL)
"""

import logging
import ssl
from functools import lru_cache
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """
    All environment variables required by the Swarm Factory backend.

    Pydantic Settings automatically reads from:
      1. Environment variables (os.environ)
      2. A .env file in the working directory

    Any field without a default is REQUIRED — the app will refuse to start
    if it's missing. This prevents silent misconfiguration in production.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,           # REDIS_URL ≠ redis_url
        extra="ignore",                # Don't error on extra .env vars
    )

    # ── Azure OpenAI ──────────────────────────────────────────────────────────
    AZURE_OPENAI_ENDPOINT: str = Field(
        ...,
        description="Full Azure OpenAI endpoint URL, e.g. https://my-resource.openai.azure.com/",
    )
    AZURE_OPENAI_API_KEY: str = Field(
        ...,
        description="Azure OpenAI API key (keep secret, never log this)",
    )
    AZURE_OPENAI_DEPLOYMENT: str = Field(
        default="gpt-4o",
        description="Azure deployment name for the primary model",
    )
    # Aliases used by individual agents and model wrappers
    AZURE_OPENAI_DEPLOYMENT_GPT4O: str = Field(
        default="gpt-4o",
        description="GPT-4o deployment name",
    )
    AZURE_OPENAI_DEPLOYMENT_PHI4: str = Field(
        default="phi-4",
        description="Phi-4 deployment name",
    )
    AZURE_OPENAI_DEPLOYMENT_MINI: str = Field(
        default="gpt-4o-mini",
        description="GPT-4o-mini deployment name",
    )
    # Azure AI Search
    AZURE_SEARCH_ENDPOINT: str = Field(default="", description="Azure AI Search endpoint")
    AZURE_SEARCH_API_KEY: str = Field(default="", description="Azure AI Search API key")
    AZURE_SEARCH_INDEX_NAME: str = Field(default="swarm-memory", description="Search index name")
    # GitHub
    GITHUB_TOKEN: str = Field(default="", description="GitHub PAT for pushing generated repos")
    GITHUB_ORG: str = Field(default="", description="GitHub org or username")
    # Azure Container Apps
    AZURE_SUBSCRIPTION_ID: str = Field(default="", description="Azure subscription ID")
    AZURE_RESOURCE_GROUP: str = Field(default="swarm-factory-rg", description="Azure resource group")
    AZURE_CONTAINER_REGISTRY: str = Field(default="", description="ACR login server")
    AZURE_CONTAINER_APP_ENV: str = Field(default="swarm-factory-env", description="Container Apps env name")
    # Session storage
    SESSION_STORE_PATH: str = Field(default="./sessions", description="Path to session JSON files")
    AZURE_STORAGE_CONNECTION_STRING: str = Field(
        default="",
        description="Azure Storage connection string for persistent project chat history",
    )
    AZURE_STORAGE_CONTAINER: str = Field(
        default="swarm-factory-state",
        description="Azure Blob container for persistent project chat history",
    )
    PROJECT_HISTORY_BLOB_NAME: str = Field(
        default="project-history/state.json",
        description="Blob name used for project/conversation/message state",
    )
    DEFAULT_USER_ID: str = Field(
        default="default-user",
        description="User id used until full user authentication is added",
    )
    PROJECT_CONTEXT_RECENT_MESSAGE_LIMIT: int = Field(
        default=10,
        description="Maximum recent conversation messages to include in project context",
    )
    PROJECT_CONTEXT_RELEVANT_MESSAGE_LIMIT: int = Field(
        default=5,
        description="Maximum older relevant messages to include in project context",
    )
    PROJECT_CONTEXT_MAX_CHARS: int = Field(
        default=12000,
        description="Maximum approximate character budget for generated project context",
    )
    PROJECT_FILES_MAX_FILE_SIZE: int = Field(
        default=256_000,
        description="Maximum project file size in bytes accepted by workspace file storage",
    )
    PROJECT_FILES_MAX_PREVIEW_CHARS: int = Field(
        default=20_000,
        description="Maximum characters returned by workspace file preview API",
    )
    PROJECT_FILES_BLOB_PREFIX: str = Field(
        default="workspace-files",
        description="Azure Blob prefix used for workspace file content",
    )
    PROJECT_CHANGES_MAX_DIFF_CHARS: int = Field(
        default=80_000,
        description="Maximum characters stored for a generated file-change diff",
    )
    PROJECT_CHANGES_MAX_PROPOSED_CONTENT_CHARS: int = Field(
        default=300_000,
        description="Maximum characters accepted for a proposed file change",
    )
    # Bing Search
    BING_SEARCH_API_KEY: str = Field(default="", description="Bing Search API key")
    AZURE_OPENAI_API_VERSION: str = Field(
        default="2024-02-01",
        description="Azure OpenAI REST API version string",
    )

    # ── Redis / Celery ────────────────────────────────────────────────────────
    REDIS_URL: str = Field(
        ...,
        description="Redis connection URL, e.g. redis://localhost:6379/0",
    )
    REDIS_SSL_CERT_REQS: str = Field(
        default="required",
        description="'required' | 'optional' | 'none' for rediss:// certificate validation",
    )

    # ── Security ──────────────────────────────────────────────────────────────
    API_KEY: str = Field(
        ...,
        description="Static API key the frontend must send in X-API-Key header",
    )
    SECRET_KEY: str = Field(
        ...,
        description="Secret key used for signing tokens / session data",
    )

    # ── Application tunables ──────────────────────────────────────────────────
    APP_ENV: str = Field(
        default="development",
        description="'development' | 'staging' | 'production'",
    )
    LOG_LEVEL: str = Field(
        default="INFO",
        description="Python logging level: DEBUG | INFO | WARNING | ERROR",
    )
    MAX_CONCURRENT_JOBS: int = Field(
        default=5,
        description="Maximum number of swarm jobs that can run in parallel",
    )
    JOB_TIMEOUT_SECONDS: int = Field(
        default=600,
        description="Hard timeout (seconds) before a job is marked failed",
    )

    # ── Rate limiting ─────────────────────────────────────────────────────────
    RATE_LIMIT_REQUESTS: int = Field(
        default=10,
        description="Maximum requests allowed per window per IP",
    )
    RATE_LIMIT_WINDOW_SECONDS: int = Field(
        default=60,
        description="Rate-limit sliding window size in seconds",
    )

    # ── Fallback model chain (see fallback_chain.py) ──────────────────────────
    FALLBACK_MODEL_PRIMARY: str = Field(
        default="gpt-4o",
        description="Primary model in the fallback chain",
    )
    FALLBACK_MODEL_SECONDARY: str = Field(
        default="phi-4",
        description="Secondary model used if primary fails",
    )
    FALLBACK_MODEL_TERTIARY: str = Field(
        default="gpt-4o-mini",
        description="Last-resort model in the fallback chain",
    )

    # ── Validators ────────────────────────────────────────────────────────────
    @field_validator("APP_ENV")
    @classmethod
    def validate_env(cls, v: str) -> str:
        """Ensure APP_ENV is one of the known values."""
        allowed = {"development", "staging", "production"}
        if v not in allowed:
            raise ValueError(f"APP_ENV must be one of {allowed}, got '{v}'")
        return v

    @field_validator("LOG_LEVEL")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Ensure LOG_LEVEL maps to a valid Python logging constant."""
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {allowed}, got '{v}'")
        return upper

    @field_validator("REDIS_SSL_CERT_REQS")
    @classmethod
    def validate_redis_ssl_cert_reqs(cls, v: str) -> str:
        """Ensure Redis TLS certificate policy is understood by redis-py/Kombu."""
        normalised = v.lower()
        allowed = {"required", "optional", "none"}
        if normalised not in allowed:
            raise ValueError(f"REDIS_SSL_CERT_REQS must be one of {allowed}, got '{v}'")
        return normalised

    @property
    def is_production(self) -> bool:
        """Convenience flag: True when running in production mode."""
        return self.APP_ENV == "production"

    @property
    def celery_broker_url(self) -> str:
        """Celery broker URL — same Redis instance we use for job state."""
        return self.REDIS_URL

    @property
    def celery_result_backend(self) -> str:
        """Celery result backend URL."""
        return self.REDIS_URL

    @property
    def redis_uses_ssl(self) -> bool:
        """True when Redis connections should use TLS."""
        return self.REDIS_URL.startswith("rediss://")

    @property
    def redis_ssl_cert_reqs(self) -> ssl.VerifyMode:
        """Return the ssl.CERT_* constant configured for rediss:// connections."""
        return {
            "required": ssl.CERT_REQUIRED,
            "optional": ssl.CERT_OPTIONAL,
            "none": ssl.CERT_NONE,
        }[self.REDIS_SSL_CERT_REQS]

    @property
    def redis_connection_kwargs(self) -> dict:
        """Extra redis-py kwargs needed for rediss:// connections."""
        if not self.redis_uses_ssl:
            return {}
        # redis-py 5.0.x only initialises RedisSSLContext.cert_reqs when
        # ssl_cert_reqs is passed as one of these strings. Passing ssl.CERT_*
        # enum values leaves the attribute unset and crashes on connect.
        return {"ssl_cert_reqs": self.REDIS_SSL_CERT_REQS}

    @property
    def celery_redis_ssl_options(self) -> dict | None:
        """TLS options Kombu/Celery require when the broker/backend URL is rediss://."""
        if not self.redis_uses_ssl:
            return None
        return {"ssl_cert_reqs": self.redis_ssl_cert_reqs}

    @property
    def safe_redis_url(self) -> str:
        """Redis URL with credentials removed for logs."""
        parsed = urlsplit(self.REDIS_URL)
        if not parsed.password:
            return self.REDIS_URL

        hostname = parsed.hostname or ""
        netloc = f"{parsed.username or ''}:***@{hostname}"
        if parsed.port:
            netloc = f"{netloc}:{parsed.port}"
        return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


# ── Singleton accessor ────────────────────────────────────────────────────────
# @lru_cache means this function is only executed ONCE per process lifetime.
# Every subsequent call returns the same Settings object — no re-reading .env.
@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Return the application-wide Settings singleton.

    Using lru_cache ensures we parse .env exactly once at startup,
    and the same object is reused everywhere. Import and call this
    function instead of instantiating Settings directly.

    Returns:
        Settings: Fully validated settings object.

    Raises:
        pydantic_core.ValidationError: If any required variable is missing or invalid.
    """
    _settings = Settings()  # type: ignore[call-arg]
    logger.info(
        "Configuration loaded",
        extra={
            "app_env": _settings.APP_ENV,
            "log_level": _settings.LOG_LEVEL,
            "max_concurrent_jobs": _settings.MAX_CONCURRENT_JOBS,
        },
    )
    return _settings


# Module-level convenience alias used throughout the codebase:
#   from core.config import settings
settings: Settings = get_settings()
