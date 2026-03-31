from __future__ import annotations

from dataclasses import dataclass

from src.settings import settings

VECTOR_DIMENSION = 1024
BATCH_SIZE = 128


@dataclass
class WeaviateConfig:
    host: str = settings.weavite_hostname
    port: int = settings.weavite_port
    grpc_port: int = settings.weavite_grpc_port
    api_key: str | None = settings.weaviate_api_key
    use_https: bool = settings.waeviate_use_https

    def get_client_args(self) -> dict[str, object]:
        host = "127.0.0.1" if self.host == "localhost" else self.host
        if host in {"localhost", "127.0.0.1"} and not self.api_key:
            return {
                "mode": "local",
                "host": host,
                "port": self.port,
                "grpc_port": self.grpc_port,
            }

        return {
            "mode": "remote",
            "http_host": host,
            "http_port": self.port,
            "http_secure": self.use_https,
            "grpc_host": host,
            "grpc_port": self.grpc_port,
            "grpc_secure": self.use_https,
            "api_key": self.api_key,
        }
