from __future__ import annotations

from src.database.session_manager import SessionManager


class _DummyWeaviateClient:
    def __init__(self, *, connected: bool = False, connect_error: Exception | None = None) -> None:
        self.connected = connected
        self.connect_error = connect_error
        self.connect_calls = 0
        self.close_calls = 0

    def is_connected(self) -> bool:
        return self.connected

    def connect(self) -> None:
        self.connect_calls += 1
        if self.connect_error is not None:
            raise self.connect_error
        self.connected = True

    def close(self) -> None:
        self.close_calls += 1
        self.connected = False


def test_get_weaviate_client_recreates_closed_client(monkeypatch) -> None:
    manager = SessionManager()
    stale_client = _DummyWeaviateClient(connect_error=RuntimeError("The `WeaviateClient` is closed."))
    fresh_client = _DummyWeaviateClient(connected=True)

    monkeypatch.setattr(
        manager,
        "_create_weaviate_client",
        lambda: fresh_client,
    )
    manager._weaviate_client = stale_client

    client = manager.get_weaviate_client()

    assert client is fresh_client
    assert stale_client.connect_calls == 1
    assert stale_client.close_calls == 1

    manager.close()
