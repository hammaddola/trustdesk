"""Process configuration from environment variables, validated at startup.

Only keys for *selected* providers are required (spec §17).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LLMProvider = Literal["ollama", "openai", "anthropic", "openai_compat", "mock"]
EmbeddingProvider = Literal["ollama", "local", "openai", "openai_compat", "cohere", "mock"]
RerankerProvider = Literal["local", "cohere", "none", "mock"]
EmailProvider = Literal["smtp", "resend", "console"]
CaptchaProvider = Literal["turnstile", "hcaptcha", "none"]
StorageProvider = Literal["local", "s3"]
RateLimitStore = Literal["postgres", "redis"]

SUPPORTED_DIMENSIONS = (384, 768, 1024, 1536)
_REPO_ROOT_ENV = Path(__file__).resolve().parents[5] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(_REPO_ROOT_ENV, ".env"), extra="ignore", case_sensitive=False)

    trustdesk_env: Literal["development", "test", "production"] = "development"
    trustdesk_mode: Literal["simple", "platform"] = "simple"

    database_url: SecretStr
    direct_database_url: SecretStr | None = None  # migrations; falls back to database_url

    # Fernet key for tenant secrets stored in the DB (webhook secrets, Slack URLs).
    trustdesk_encryption_key: SecretStr | None = None
    # Required to create the first owner account through the Setup Wizard.
    trustdesk_setup_token: SecretStr | None = None

    llm_provider: LLMProvider = "ollama"
    llm_model: str = "llama3.1:8b"
    # For "thinking" models (e.g. Gemini 2.5+/3.x via openai_compat). Hidden reasoning tokens count against
    # MAX_ANSWER_TOKENS and can truncate answers; "none" disables it (grounded answers don't need it).
    llm_reasoning_effort: Literal["none", "low", "medium", "high"] | None = None
    embedding_provider: EmbeddingProvider = "ollama"
    embedding_model: str = "bge-m3"
    embedding_dimension: int = 1024
    reranker_provider: RerankerProvider = "local"
    reranker_model: str = "BAAI/bge-reranker-v2-m3"

    ollama_base_url: str = "http://localhost:11434"
    openai_api_key: SecretStr | None = None
    openai_base_url: str | None = None  # set for openai_compat (Groq, vLLM, LM Studio, ...)
    anthropic_api_key: SecretStr | None = None
    cohere_api_key: SecretStr | None = None

    email_provider: EmailProvider = "console"
    resend_api_key: SecretStr | None = None
    email_from: str | None = None
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None

    captcha_provider: CaptchaProvider = "none"
    turnstile_secret_key: SecretStr | None = None
    turnstile_site_key: str | None = None  # public
    hcaptcha_site_key: str | None = None  # public
    hcaptcha_secret_key: SecretStr | None = None

    storage_provider: StorageProvider = "local"
    storage_local_dir: str = "./data/uploads"

    rate_limit_store: RateLimitStore = "postgres"
    redis_url: SecretStr | None = None

    langfuse_public_key: str | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_host: str | None = None

    # Comma-separated; admin origin(s). Widget origins are per tenant in tenant_settings.
    allowed_origins: str = "http://localhost:3000"
    monthly_spend_limit: float = Field(default=0, ge=0)  # 0 = no global cap
    max_answer_tokens: int = Field(default=600, ge=50, le=4000)
    confidence_threshold: float = Field(default=0.35, ge=0, le=1)

    max_upload_bytes: int = 20 * 1024 * 1024
    max_request_bytes: int = 64 * 1024
    session_ttl_hours: int = 12

    @field_validator("embedding_dimension")
    @classmethod
    def _dimension_supported(cls, v: int) -> int:
        if v not in SUPPORTED_DIMENSIONS:
            raise ValueError(f"EMBEDDING_DIMENSION must be one of {SUPPORTED_DIMENSIONS} (indexed dimensions)")
        return v

    @property
    def admin_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def email_delivery_enabled(self) -> bool:
        # The console provider only logs; in production that means the email channel is off, not "sent".
        return not (self.is_production and self.email_provider == "console")

    @property
    def is_production(self) -> bool:
        return self.trustdesk_env == "production"

    @model_validator(mode="after")
    def _require_selected_provider_keys(self) -> Settings:
        missing: list[str] = []
        need = {
            "OPENAI_API_KEY": self.openai_api_key is None
            and (self.llm_provider == "openai" or self.embedding_provider == "openai"),
            "ANTHROPIC_API_KEY": self.anthropic_api_key is None and self.llm_provider == "anthropic",
            "COHERE_API_KEY": self.cohere_api_key is None
            and (self.embedding_provider == "cohere" or self.reranker_provider == "cohere"),
            "OPENAI_BASE_URL": self.openai_base_url is None
            and (self.llm_provider == "openai_compat" or self.embedding_provider == "openai_compat"),
            "RESEND_API_KEY": self.resend_api_key is None and self.email_provider == "resend",
            "SMTP_HOST": self.smtp_host is None and self.email_provider == "smtp",
            "TURNSTILE_SECRET_KEY": self.turnstile_secret_key is None and self.captcha_provider == "turnstile",
            "HCAPTCHA_SECRET_KEY": self.hcaptcha_secret_key is None and self.captcha_provider == "hcaptcha",
            "REDIS_URL": self.redis_url is None and self.rate_limit_store == "redis",
        }
        missing = [k for k, is_missing in need.items() if is_missing]
        if self.is_production:
            if self.trustdesk_encryption_key is None:
                missing.append("TRUSTDESK_ENCRYPTION_KEY")
            mocks = [p for p in (self.llm_provider, self.embedding_provider, self.reranker_provider) if p == "mock"]
            if mocks:
                raise ValueError("mock providers are for development/tests only and are refused in production")
            if any(o == "*" for o in self.admin_origins):
                raise ValueError("ALLOWED_ORIGINS must not contain '*'")
        if missing:
            raise ValueError("missing required environment variables for the selected providers: " + ", ".join(missing))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # values come from the environment
