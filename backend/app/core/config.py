from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    app_secret_key: str = "change-me"
    app_encryption_key: str = ""
    frontend_url: str = "http://localhost:5173"
    app_timezone: str = "America/Argentina/Buenos_Aires"
    app_public_base_url: str = ""

    database_url: str

    cors_origins: str = "http://localhost:5173"

    ml_api_base_url: str = "https://api.mercadolibre.com"
    ml_auth_base_url: str = "https://auth.mercadolibre.com.ar"
    ml_site_id: str = "MLA"
    ml_client_id: str = ""
    ml_client_secret: str = ""
    ml_redirect_uri: str = ""
    ml_metadata_ttl_seconds: int = 86400
    ml_keyword_trends_ttl_seconds: int = 86400
    ml_request_timeout_seconds: float = 20.0
    ml_live_publication_enabled: bool = False

    keyword_embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    keyword_max_trends: int = 50
    keyword_max_selected_terms: int = 12
    keyword_min_semantic_similarity: float = 0.35

    openai_api_key: str = ""
    openai_model: str = ""
    openai_request_timeout_seconds: float = 45.0

    upload_dir: Path = Path("./uploads")
    max_upload_bytes: int = 10 * 1024 * 1024
    ml_image_min_side_px: int = 500
    ml_image_recommended_side_px: int = 1200
    ml_image_allowed_formats_csv: str = "JPEG,JPG,PNG"

    worker_poll_seconds: float = 2.0
    worker_max_attempts: int = 4
    worker_base_backoff_seconds: float = 2.0
    worker_heartbeat_stale_seconds: float = 30.0


    @property
    def ml_image_allowed_formats(self) -> set[str]:
        return {
            value.strip().upper()
            for value in self.ml_image_allowed_formats_csv.split(",")
            if value.strip()
        }

    @property
    def public_base_url(self) -> str:
        explicit = self.app_public_base_url.strip().rstrip("/")
        if explicit:
            return explicit
        parts = urlsplit(self.ml_redirect_uri)
        if parts.scheme in {"http", "https"} and parts.netloc:
            return f"{parts.scheme}://{parts.netloc}"
        return ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.cors_origins.split(",")
            if origin.strip()
        ]

    @property
    def ml_oauth_configured(self) -> bool:
        return bool(self.ml_client_id and self.ml_client_secret and self.ml_redirect_uri)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    return settings
