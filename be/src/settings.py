from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.services.key_vault.client import InfisicalClient

load_dotenv(override=False)

@lru_cache(maxsize=1)
def get_infisical_client() -> InfisicalClient:
    """Lazily create the Infisical client so imports stay test-safe."""
    return InfisicalClient()

class Settings(BaseSettings):
    environment: str = Field(default="development", alias="ENVIRONMENT")

    app_name: str = Field(default="DigiGO Backend", alias="APP_NAME")
    api_base_path: str = Field(default="/api/v1", alias="API_BASE_PATH")
    jwt_secret: str = Field(default="dev-secret", alias="JWT_SECRET")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    jwt_expiration_minutes: int = Field(default=480, alias="JWT_EXPIRATION_MINUTES")
    audit_retention_days: int = Field(default=365, alias="AUDIT_RETENTION_DAYS")
    audit_admin_party_ids_raw: str = Field(default="", alias="AUDIT_ADMIN_PARTY_IDS")

    database_url: str = Field(
        default="sqlite:///./data/digigo.db",
        alias="DATABASE_URL",
    )
    database_echo: bool = Field(default=False, alias="DATABASE_ECHO")

    storage_root: Path = Field(default=Path("./data/runtime"), alias="STORAGE_ROOT")
    logs_root: Path = Field(default=Path("./logs"), alias="LOGS_ROOT")
    mock_registry_path: Path = Field(
        default=Path("./data/mock_registry.json"),
        alias="MOCK_REGISTRY_PATH",
    )

    keydb_host: str = Field(default="localhost", alias="KEYDB_HOST")
    keydb_port: int = Field(default=6379, alias="KEYDB_PORT")
    keydb_password: str | None = Field(default=None, alias="KEYDB_PASSWORD")
    keydb_queue_db: int = Field(default=1, alias="KEYDB_QUEUE_DB")

    weavite_hostname: str = Field(default="localhost", alias="WEAVIATE_HOSTNAME")
    weavite_port: int = Field(default=8080, alias="WEAVIATE_PORT")
    weavite_grpc_port: int = Field(default=50051, alias="WEAVIATE_GRPC_PORT")
    waeviate_use_https: bool = Field(default=False, alias="WEAVIATE_USE_HTTPS")
    weaviate_api_key: str | None = Field(default=None, alias="WEAVIATE_API_KEY")

    tasks_eager: bool = Field(default=False, alias="TASKS_EAGER")
    indexing_batch_size: int = Field(default=16, alias="INDEXING_BATCH_SIZE")
    sync_batch_size: int = Field(default=128, alias="SYNC_BATCH_SIZE")
    def _get_infisical_secret(self, secret_name: str, *, path: str) -> str:
        return get_infisical_client().get_secret(secret_name, path=path)

    @property
    def gemini_api_key(self) -> str:
        return self._get_infisical_secret("GEMINI_API_KEY", path="/AI")

    @property
    def jina_api_key(self) -> str:
        return self._get_infisical_secret("JINA_API_KEY", path="/AI")

    @property
    def ms_doc_intel_key(self) -> str:
        return self._get_infisical_secret("MS_DOC_INTEL_KEY", path="/Microsoft")

    @property
    def ms_doc_intel_endpoint(self) -> str:
        return self._get_infisical_secret("MS_DOC_INTEL_ENDPOINT", path="/Microsoft")
    
    google_application_credentials: str | None = Field(
        default=None,
        alias="GOOGLE_APPLICATION_CREDENTIALS",
    )
    google_project_id: str | None = Field(default=None, alias="GOOGLE_PROJECT_ID")
    google_location: str = Field(default="europe-west4", alias="GOOGLE_LOCATION")

    arq_job_timeout_seconds: int = Field(
        default=3600,
        alias="ARQ_JOB_TIMEOUT_SECONDS",
    )
    gemini_model: str = Field(default="gemini-3-flash-preview", alias="GEMINI_MODEL")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        populate_by_name=True,
        extra="ignore",
    )

    def ensure_runtime_dirs(self) -> None:
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self.logs_root.mkdir(parents=True, exist_ok=True)

    @property
    def audit_admin_party_ids(self) -> list[str]:
        return [
            party_id.strip()
            for party_id in self.audit_admin_party_ids_raw.split(",")
            if party_id.strip()
        ]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_runtime_dirs()
    return settings


settings = get_settings()
