from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from src.services.dsgo.auth import DSGOAuth
from src.services.dsgo.config import get_config
from src.services.dsgo.registry import DSGORegistry, Party

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Participant:
    party_id: str
    name: str
    dsgo_roles: list[str]
    membership_status: str = "Active"

    @property
    def is_service_consumer(self) -> bool:
        return "ServiceConsumer" in self.dsgo_roles

    @property
    def is_service_provider(self) -> bool:
        return "ServiceProvider" in self.dsgo_roles


@dataclass
class LiveParticipantRegistry:
    """Fetches participants from the real DSGO acceptance environment,
    with a simple TTL cache to avoid hitting the API on every request."""

    _cache: list[Participant] = field(default_factory=list)
    _cache_time: float = 0
    _cache_ttl: float = 300  # 5 minutes

    def _get_dsgo_client(self) -> DSGORegistry:
        config = get_config()
        auth = DSGOAuth(**config)
        return DSGORegistry(auth)

    def _refresh_cache(self) -> None:
        if self._cache and (time.time() - self._cache_time) < self._cache_ttl:
            return
        try:
            logger.info("Fetching participants from DSGO acceptance registry...")
            client = self._get_dsgo_client()
            parties: list[Party] = client.list_parties(active_only=True)
            self._cache = [
                Participant(
                    party_id=p.id,
                    name=p.name,
                    dsgo_roles=p.roles,
                    membership_status=p.membership_status or "Active",
                )
                for p in parties
            ]
            self._cache_time = time.time()
            logger.info("Loaded %d participants from DSGO registry", len(self._cache))
        except Exception:
            logger.exception("Failed to fetch DSGO participants, using cached data")
            if not self._cache:
                # Absolute fallback so the app doesn't break
                self._cache = [
                    Participant(
                        party_id="did:ishare:EU.NL.NTRNL-98499327",
                        name="Vondr B.V.",
                        dsgo_roles=["ServiceProvider", "ServiceConsumer"],
                    ),
                ]

    def list_participants(
        self,
        *,
        search: str | None = None,
        required_dsgo_role: str | None = None,
    ) -> list[Participant]:
        self._refresh_cache()
        items = self._cache
        if search:
            lowered = search.lower()
            items = [
                item
                for item in items
                if lowered in item.name.lower() or lowered in item.party_id.lower()
            ]
        if required_dsgo_role:
            items = [
                item for item in items if required_dsgo_role in item.dsgo_roles
            ]
        return items

    def get_participant(self, party_id: str) -> Participant | None:
        self._refresh_cache()
        for item in self._cache:
            if item.party_id == party_id:
                return item
        return None


registry = LiveParticipantRegistry()
