# src\database\keydb\keydb_config.py
from __future__ import annotations

from attrs import Factory, define


@define
class KeyDBConfig:
    """
    Configuration class for KeyDB connection, loaded from environment variables.
    """

    host: str = Factory(lambda: _get_settings().keydb_host)
    port: int = Factory(lambda: int(_get_settings().keydb_port))
    password: str | None = Factory(lambda: _get_settings().keydb_password)
    db: int = Factory(lambda: _get_settings().keydb_queue_db)

    def get_connection_kwargs(self) -> dict:
        host = "127.0.0.1" if self.host == "localhost" else self.host
        return {
            "host": host,
            "port": self.port,
            "password": self.password,
            "db": self.db,
            "decode_responses": False,
        }


def _get_settings():  # noqa: ANN202
    from src.settings import settings

    return settings
