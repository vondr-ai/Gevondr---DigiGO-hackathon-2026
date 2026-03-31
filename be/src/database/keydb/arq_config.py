# src\database\keydb\arq_config.py
from __future__ import annotations

from arq.connections import RedisSettings

from src.database.keydb.keydb_config import KeyDBConfig
from src.settings import settings


def get_arq_redis_settings(db: int | None = None) -> RedisSettings:
    """
    Creates arq RedisSettings from the centralized KeyDBConfig.
    This ensures all workers and producers connect to the same Redis instance.
    """
    keydb_config = KeyDBConfig()

    if db is None:
        db = settings.keydb_queue_db

    return RedisSettings(
        host=keydb_config.host,
        port=keydb_config.port,
        password=keydb_config.password,
        database=db,
    )
