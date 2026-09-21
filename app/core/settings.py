"""Centralized settings. Everything configurable lives here and comes from .env."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    # app
    APP_ENV: str = "development"
    APP_HOST: str = "127.0.0.1"
    APP_PORT: int = 8000
    LOG_LEVEL: str = "INFO"

    # telegram
    TELEGRAM_BOT_TOKEN: str = ""

    # nvidia build / llm
    NVIDIA_API_KEY: str = ""
    NVIDIA_BASE_URL: str = "https://integrate.api.nvidia.com/v1"
    NVIDIA_MODEL: str = ""
    NVIDIA_TIMEOUT: int = 60
    LLM_MODE: str = "auto"  # auto | nvidia | deterministic
    # Ordered provider chain (.env only). Unknown names are ignored.
    LLM_PROVIDERS: str = "nvidia"
    # LLM-first loop knobs (cost control + failure tolerance)
    LLM_MAX_TOOL_ROUNDS: int = 4
    LLM_MAX_TOOL_CALLS_PER_TURN: int = 8
    LLM_HISTORY_TURNS: int = 8
    LLM_TOOL_RESULT_MAX_CHARS: int = 4000
    LLM_TEMPERATURE: float = 0.2
    LLM_MAX_TOKENS: int = 4000
    LLM_RETRY_MAX: int = 3
    # Reasoning effort level for models that support it (NVIDIA: high | medium | low | minimal | none)
    LLM_REASONING_LEVEL: str = "high"

    # embeddings
    EMBEDDING_PROVIDER: str = "auto"  # auto | nvidia | local
    EMBEDDING_DIM: int = 2048
    EMBEDDING_MODEL: str = "nvidia/nemotron-3-embed-1b"

    # database
    DATABASE_URL: str = "postgresql+psycopg://inmobiliaria:inmobiliaria@127.0.0.1:5432/inmobiliaria"
    TEST_DATABASE_URL: str = ""
    PGDATA: str = "./pgdata"

    # redis
    REDIS_URL: str = "redis://127.0.0.1:6379/0"

    # storage
    STORAGE_PATH: str = "./storage"
    DOCUMENTS_PATH: str = "./documents"
    MAX_UPLOAD_MB: int = 15

    # admin / api
    ADMIN_HOST: str = "127.0.0.1"
    ADMIN_PORT: int = 3000
    ADMIN_TOKEN: str = "changeme-admin-token"
    API_BASE_URL: str = "http://127.0.0.1:8000"

    # ux
    RATE_LIMIT_PER_MINUTE: int = 20

    # web search tool (agent decides when to use it; disabled = honest error)
    WEB_SEARCH_ENABLED: bool = True
    WEB_SEARCH_TIMEOUT: float = 10.0
    WEB_SEARCH_MAX_RESULTS: int = 5
    WEB_SEARCH_SNIPPET_MAX_CHARS: int = 400

    # retry configuration
    RETRY_TOOL_EXEC_MAX_ATTEMPTS: int = 3
    RETRY_LLM_CALL_MAX_ATTEMPTS: int = 3
    RETRY_READ_MAX_ATTEMPTS: int = 3
    RETRY_WRITE_MAX_ATTEMPTS: int = 2
    RETRY_FILE_IO_MAX_ATTEMPTS: int = 3
    RETRY_BASE_DELAY: float = 0.5
    RETRY_MAX_DELAY: float = 30.0
    RETRY_JITTER_FACTOR: float = 0.3

    # timeout configuration
    TOOL_TIMEOUT: float = 30.0
    LLM_TIMEOUT: float = 60.0
    DB_TIMEOUT: float = 10.0

    # timezone
    TZ: str = "America/Bogota"

    # jwt
    JWT_SECRET: str = "changeme-jwt-secret"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # --- derived helpers -------------------------------------------------
    @property
    def storage_dir(self) -> Path:
        return Path(self.STORAGE_PATH)

    @property
    def documents_dir(self) -> Path:
        return Path(self.DOCUMENTS_PATH)

    @property
    def nvidia_configured(self) -> bool:
        return bool(self.NVIDIA_API_KEY and self.NVIDIA_MODEL)

    @property
    def llm_is_nvidia(self) -> bool:
        """True when the LLM is the configured brain (semantics of LLM_MODE).

        - ``nvidia``: fuerza proveedor NVIDIA (falla si no hay credenciales).
        - ``deterministic``: nunca llama a la red; motor determinista como cerebro.
        - ``auto``: LLM-FIRST — NVIDIA es el cerebro principal si está configurado.
          No significa «determinista y consultar al LLM solo si hace falta».
        """
        if self.LLM_MODE == "nvidia":
            return True
        if self.LLM_MODE == "deterministic":
            return False
        return self.nvidia_configured

    @property
    def llm_first_enabled(self) -> bool:
        """The LLM orchestrates the turn; deterministic mode is only the failsafe."""
        return self.llm_is_nvidia and self.nvidia_configured

    @property
    def embedding_is_nvidia(self) -> bool:
        if self.EMBEDDING_PROVIDER == "nvidia":
            return self.nvidia_configured
        if self.EMBEDDING_PROVIDER == "local":
            return False
        return self.nvidia_configured  # auto

    def ensure_dirs(self) -> None:
        (self.storage_dir / "documents").mkdir(parents=True, exist_ok=True)
        (self.storage_dir / "properties").mkdir(parents=True, exist_ok=True)
        (self.documents_dir / "inbox").mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s
