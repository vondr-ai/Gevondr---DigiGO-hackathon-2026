from __future__ import annotations

from src.database.models import *  # noqa: F401,F403
from src.database.postgres.connection.base import Base
from src.database.session_manager import get_session_manager


def init_database() -> None:
    session_manager = get_session_manager()
    Base.metadata.create_all(bind=session_manager.engine)
