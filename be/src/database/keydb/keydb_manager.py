from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Generator

from redis import Redis

from src.database.keydb.keydb_config import KeyDBConfig

log = logging.getLogger(__name__)


class KeyDBManager:
    """A manager for handling Redis connections and operations."""

    def __init__(self, config: KeyDBConfig | None = None):
        if config is None:
            config = KeyDBConfig()
        self.config = config
        self._client: Redis | None = None

    def _initialize_client(self) -> None:
        """Initializes the Redis client if not already initialized."""
        if self._client is None:
            try:
                connection_kwargs = self.config.get_connection_kwargs()
                self._client = Redis(**connection_kwargs)
                self._client.ping()
                log.info(
                    f"Successfully connected to KeyDB at {self.config.host}:{self.config.port}"
                )
            except Exception as e:
                log.error(
                    f"An unexpected error occurred during KeyDB initialization: {e}"
                )
                self._client = None
                raise

    @property
    def client(self) -> Redis:
        """Provides access to the Redis client, initializing it if necessary."""
        if self._client is None:
            self._initialize_client()
        # The client should be initialized at this point.
        # If it's still None, _initialize_client would have raised an exception.
        return self._client  # type: ignore

    @contextmanager
    def get_client(self) -> Generator[Redis, None, None]:
        """A context manager to safely get and use the Redis client."""
        try:
            yield self.client
        finally:
            # The connection pool handles connection cleanup, so we don't need to close it here.
            pass

    def close(self) -> None:
        """Closes the Redis client connection."""
        if self._client:
            self._client.close()
            log.info("KeyDB connection closed.")
            self._client = None

    def __enter__(self):
        self._initialize_client()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
