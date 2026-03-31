"""DSGO iSHARE authentication client for the Participant Registry."""

import logging
import re
import time
from pathlib import Path

import jwt
import requests

logger = logging.getLogger(__name__)


class DSGOAuth:
    """Handles iSHARE OAuth2 authentication with the DSGO Participant Registry."""

    def __init__(
        self,
        client_id: str,
        private_key_path: str,
        certificate_path: str,
        registry_url: str,
        registry_party_id: str,
    ):
        self.client_id = client_id
        self.registry_url = registry_url.rstrip("/")
        self.registry_party_id = registry_party_id

        self._private_key = Path(private_key_path).read_text()
        self._x5c = self._load_certificate_chain(certificate_path)

        self._access_token: str | None = None
        self._token_expires_at: float = 0

    @staticmethod
    def _load_certificate_chain(path: str) -> list[str]:
        pem_data = Path(path).read_text()
        certs = re.findall(
            r"-----BEGIN CERTIFICATE-----\n(.+?)\n-----END CERTIFICATE-----",
            pem_data,
            re.DOTALL,
        )
        return [cert.replace("\n", "") for cert in certs]

    def _create_client_assertion(self) -> str:
        now = int(time.time())
        payload = {
            "iss": self.client_id,
            "sub": self.client_id,
            "aud": self.registry_party_id,
            "jti": str(now),
            "iat": now,
            "nbf": now,
            "exp": now + 30,
        }
        headers = {
            "x5c": self._x5c,
            "alg": "RS256",
            "typ": "JWT",
        }
        return jwt.encode(
            payload, self._private_key, algorithm="RS256", headers=headers
        )

    def get_access_token(self) -> str:
        """Get a valid access token, refreshing if expired."""
        if self._access_token and time.time() < self._token_expires_at:
            return self._access_token

        assertion = self._create_client_assertion()

        response = requests.post(
            f"{self.registry_url}/connect/token",
            data={
                "grant_type": "client_credentials",
                "scope": "iSHARE",
                "client_id": self.client_id,
                "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
                "client_assertion": assertion,
            },
        )
        if not response.ok:
            logger.error(
                "iSHARE token request failed: status=%s body=%s client_id=%s registry_party_id=%s url=%s",
                response.status_code, response.text, self.client_id, self.registry_party_id, self.registry_url,
            )
        response.raise_for_status()
        data = response.json()

        self._access_token = data["access_token"]
        self._token_expires_at = time.time() + data.get("expires_in", 3600) - 60

        return self._access_token
