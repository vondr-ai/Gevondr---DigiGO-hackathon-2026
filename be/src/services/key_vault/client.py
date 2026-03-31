from __future__ import annotations

import logging
from typing import cast

import httpx

from src.database.keydb.keydb_manager import KeyDBManager
from src.services.key_vault.config import InfisicalConfig

logger = logging.getLogger(__name__)

_CACHE_PREFIX = "infisical:"
_DEFAULT_TTL = 3600


class InfisicalClient:
    """Thin httpx-based client for fetching secrets from Infisical."""

    def __init__(
        self,
        config: InfisicalConfig | None = None,
        keydb_manager: KeyDBManager | None = None,
        cache_ttl: int = _DEFAULT_TTL,
    ) -> None:
        self._config = config or InfisicalConfig()
        self._access_token: str | None = None
        self._keydb = keydb_manager
        self._cache_ttl = cache_ttl
        self._http = httpx.Client(base_url=self._config.endpoint, timeout=10)

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _cache_key(secret_name: str, path: str, environment: str) -> str:
        return f"{_CACHE_PREFIX}{environment}:{path}:{secret_name}"

    def _cache_get(self, key: str) -> str | None:
        if self._keydb is None:
            return None
        try:
            with self._keydb.get_client() as client:
                raw = cast(bytes | str | None, client.get(key))
                if raw is None:
                    return None
                return raw.decode() if isinstance(raw, bytes) else raw
        except Exception as exc:  # noqa: BLE001 - fail open
            logger.warning("KeyDB cache read failed for %s: %s", key, exc)
            return None

    def _cache_set(self, key: str, value: str) -> None:
        if self._keydb is None:
            return
        try:
            with self._keydb.get_client() as client:
                client.setex(key, self._cache_ttl, value)
        except Exception as exc:  # noqa: BLE001 - fail open
            logger.warning("KeyDB cache write failed for %s: %s", key, exc)

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def _ensure_authenticated(self) -> None:
        if self._access_token is not None:
            return

        resp = self._http.post(
            "/api/v1/auth/universal-auth/login",
            json={
                "clientId": self._config.client_id,
                "clientSecret": self._config.client_secret,
            },
        )
        resp.raise_for_status()
        self._access_token = resp.json()["accessToken"]
        logger.info("Authenticated with Infisical")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_secret(
        self,
        secret_name: str,
        path: str = "/",
    ) -> str:
        """Return the value of a single secret from Infisical.

        Args:
            secret_name: Name of the secret (e.g. "GEMINI_API_KEY").
            path: Folder path in Infisical (e.g. "/AI").

        Returns:
            The secret value as a string.
        """
        environment = self._config.environment
        if environment == "azure-prod":
            environment = "prod"
        elif environment == "azure-dev":
            environment = "dev"

        cache_key = self._cache_key(secret_name, path, environment)
        cached = self._cache_get(cache_key)
        if cached is not None:
            logger.debug("Cache hit for secret %s", secret_name)
            return cached

        self._ensure_authenticated()

        resp = self._http.get(
            f"/api/v3/secrets/raw/{secret_name}",
            headers={"Authorization": f"Bearer {self._access_token}"},
            params={
                "workspaceId": self._config.project_id,
                "environment": environment,
                "secretPath": path,
            },
        )
        resp.raise_for_status()
        value: str = resp.json()["secret"]["secretValue"]
        self._cache_set(cache_key, value)
        return value
