from __future__ import annotations
from dataclasses import dataclass
from src.settings import settings


@dataclass
class PostgresConfig:
    user: str = settings.postgres_user
    password: str = settings.postgres_password
    port: int = settings.postgres_port
    hostname: str = settings.postgres_hostname
    database: str = settings.postgres_db
    pool_size: int = settings.postgres_pool_size
    max_overflow: int = settings.postgres_max_overflow

    def get_url(self) -> str:
        """Function that gets the connection URL for the database."""
        host = "127.0.0.1" if self.hostname == "localhost" else self.hostname
        return f"postgresql://{self.user}:{self.password}@{host}:{self.port}/{self.database}"


@dataclass
class ExcelPostgresConfig(PostgresConfig):
    database: str = settings.postgres_excel_db
