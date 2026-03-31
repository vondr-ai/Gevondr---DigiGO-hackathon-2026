"""Client for the DSGO Participant Registry API."""

from dataclasses import dataclass

import requests

from src.services.dsgo.auth import DSGOAuth


@dataclass
class Party:
    id: str
    name: str
    also_known_as: list[str]
    claims: list[dict]

    @property
    def roles(self) -> list[str]:
        return [
            c["roleId"]
            for c in self.claims
            if c.get("type") == "dataspaceRole" and c.get("status") == "Active"
        ]

    @property
    def is_service_provider(self) -> bool:
        return "ServiceProvider" in self.roles

    @property
    def is_service_consumer(self) -> bool:
        return "ServiceConsumer" in self.roles

    @property
    def membership_status(self) -> str | None:
        for c in self.claims:
            if c.get("type") == "dataspaceMembership":
                return c.get("status")
        return None


class DSGORegistry:
    """Client for querying the DSGO Participant Registry."""

    def __init__(self, auth: DSGOAuth):
        self.auth = auth
        self.base_url = auth.registry_url

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.auth.get_access_token()}"}

    def list_parties(self, active_only: bool = True) -> list[Party]:
        """List all parties in the DSGO registry."""
        parties = []
        page = 1

        while True:
            response = requests.get(
                f"{self.base_url}/api/v1/parties",
                params={
                    "format": "json",
                    "activeOnly": str(active_only).lower(),
                    "page": page,
                    "size": 50,
                },
                headers=self._headers(),
            )
            response.raise_for_status()
            data = response.json()

            for p in data.get("data", []):
                parties.append(
                    Party(
                        id=p["id"],
                        name=p["name"],
                        also_known_as=p.get("alsoKnownAs", []),
                        claims=p.get("claims", []),
                    )
                )

            if not data.get("next"):
                break
            page += 1

        return parties

    def get_party(self, party_id: str) -> Party:
        """Get details of a single party by DID."""
        response = requests.get(
            f"{self.base_url}/api/v1/parties/{party_id}",
            params={"format": "json"},
            headers=self._headers(),
        )
        response.raise_for_status()
        p = response.json()

        return Party(
            id=p["id"],
            name=p["name"],
            also_known_as=p.get("alsoKnownAs", []),
            claims=p.get("claims", []),
        )
