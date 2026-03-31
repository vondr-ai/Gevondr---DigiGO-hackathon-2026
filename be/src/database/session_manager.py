from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from typing import Generator

import weaviate
from redis import Redis
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker
from weaviate.connect import ConnectionParams

from src.database.keydb.keydb_config import KeyDBConfig
from src.database.keydb.keydb_manager import KeyDBManager
from src.database.weaviate.connection.weaviate_config import WeaviateConfig
from src.settings import settings

_session_manager: SessionManager | None = None
_lock = threading.Lock()
logger = logging.getLogger(__name__)


class SessionManager:
    def __init__(self) -> None:
        connect_args: dict[str, object] = {}
        if settings.database_url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        self._engine = create_engine(
            settings.database_url,
            echo=settings.database_echo,
            future=True,
            connect_args=connect_args,
        )
        self._session_factory = sessionmaker(
            bind=self._engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
            future=True,
        )
        self._weaviate_client: weaviate.WeaviateClient | None = None
        self._weaviate_lock = threading.Lock()
        self._keydb_manager = KeyDBManager(
            KeyDBConfig(db=settings.keydb_queue_db),
        )

    @property
    def engine(self):
        return self._engine

    @contextmanager
    def get_pg_session(self) -> Generator[Session, None, None]:
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _create_weaviate_client(self) -> weaviate.WeaviateClient:
        config = WeaviateConfig()
        client_args = config.get_client_args()
        if client_args.get("mode") == "local":
            return weaviate.connect_to_local(
                host=client_args["host"],
                port=client_args["port"],
                grpc_port=client_args["grpc_port"],
                skip_init_checks=True,
            )
        connection_params = ConnectionParams.from_params(
            http_host=client_args["http_host"],
            http_port=client_args["http_port"],
            http_secure=client_args["http_secure"],
            grpc_host=client_args["grpc_host"],
            grpc_port=client_args["grpc_port"],
            grpc_secure=client_args["grpc_secure"],
        )
        auth_client_secret = None
        if client_args.get("api_key"):
            from weaviate.auth import AuthApiKey

            auth_client_secret = AuthApiKey(api_key=client_args["api_key"])
        client = weaviate.WeaviateClient(
            connection_params=connection_params,
            auth_client_secret=auth_client_secret,
        )
        client.connect()
        return client

    def get_weaviate_client(self) -> weaviate.WeaviateClient:
        with self._weaviate_lock:
            if self._weaviate_client is not None:
                try:
                    if self._weaviate_client.is_connected():
                        return self._weaviate_client
                    self._weaviate_client.connect()
                    if self._weaviate_client.is_connected():
                        return self._weaviate_client
                except Exception as exc:
                    logger.warning("Recreating stale Weaviate client after reconnect failure: %s", exc)
                    try:
                        self._weaviate_client.close()
                    except Exception:
                        logger.debug("Ignoring error while closing stale Weaviate client", exc_info=True)
                    self._weaviate_client = None

            self._weaviate_client = self._create_weaviate_client()
        return self._weaviate_client

    @contextmanager
    def get_keydb_client(self) -> Generator[Redis, None, None]:
        with self._keydb_manager.get_client() as client:
            yield client

    def close(self) -> None:
        if self._weaviate_client is not None:
            self._weaviate_client.close()
            self._weaviate_client = None
        self._keydb_manager.close()
        self._engine.dispose()


def get_session_manager() -> SessionManager:
    global _session_manager
    if _session_manager is None:
        with _lock:
            if _session_manager is None:
                _session_manager = SessionManager()
    return _session_manager
