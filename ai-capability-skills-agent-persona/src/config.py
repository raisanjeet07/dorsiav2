"""Application configuration — loaded from environment variables."""

from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """All settings are overridable via env vars prefixed with CAPS_."""

    # Service
    host: str = "0.0.0.0"
    port: int = 8100
    debug: bool = False
    log_level: str = "INFO"

    # Extension directories
    defaults_dir: str = str(Path(__file__).resolve().parent.parent / "defaults")
    extensions_dir: str = str(Path(__file__).resolve().parent.parent / "config" / "extensions")

    # CLI Agent Gateway connection
    gateway_http_url: str = "http://localhost:8080"
    gateway_sync_on_startup: bool = True
    gateway_sync_timeout_seconds: int = 10

    # Hot-reload
    hot_reload_enabled: bool = True
    hot_reload_debounce_seconds: float = 1.0

    # Persistence (optional — extensions are primarily in-memory + YAML)
    persist_api_extensions: bool = True
    api_extensions_dir: str = str(Path(__file__).resolve().parent.parent / "config" / "extensions")

    model_config = {"env_prefix": "CAPS_"}


settings = Settings()
