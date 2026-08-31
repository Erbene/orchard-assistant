"""Zone business logic.

Decoupled from HTTP: methods take/return plain values and Pydantic models,
raise domain exceptions, and never touch ``fastapi`` or ``Request``. This is
what lets a future MCP tool call ``ZoneService.create_zone(...)`` directly.
"""
from __future__ import annotations

import sqlite3

from ..repositories.zone_repository import ZoneRepository
from ..schemas.zone import ZoneCreate, ZoneRead, ZoneUpdate
from .exceptions import ConflictError, DomainValidationError, NotFoundError
from .validators import ValidationAgent


class ZoneService:
    def __init__(self, repo: ZoneRepository, validator: ValidationAgent) -> None:
        self._repo = repo
        self._validator = validator

    async def list_zones(self) -> list[ZoneRead]:
        return [ZoneRead.model_validate(r) for r in self._repo.list()]

    async def get_zone(self, zone_id: int) -> ZoneRead:
        row = self._repo.get(zone_id)
        if row is None:
            raise NotFoundError(f"zone {zone_id} not found")
        return ZoneRead.model_validate(row)

    async def create_zone(self, payload: ZoneCreate) -> ZoneRead:
        soil = await self._normalize("soil_drainage", payload.soil_drainage)
        source = await self._normalize("source", payload.source)
        row = self._repo.create(payload.name.strip(), soil, source)
        return ZoneRead.model_validate(row)

    async def update_zone(self, zone_id: int, payload: ZoneUpdate) -> ZoneRead:
        if self._repo.get(zone_id) is None:
            raise NotFoundError(f"zone {zone_id} not found")

        patch = payload.model_dump(exclude_unset=True)
        for key in ("soil_drainage", "source"):
            if key in patch:
                patch[key] = await self._normalize(key, patch[key])
        if "name" in patch and patch["name"] is not None:
            patch["name"] = patch["name"].strip()

        row = self._repo.update(zone_id, patch)
        return ZoneRead.model_validate(row)

    async def delete_zone(self, zone_id: int) -> None:
        if self._repo.get(zone_id) is None:
            raise NotFoundError(f"zone {zone_id} not found")
        try:
            self._repo.delete(zone_id)
        except sqlite3.IntegrityError as exc:
            raise ConflictError(
                f"zone {zone_id} is still referenced by one or more trees"
            ) from exc

    # -- helpers ---------------------------------------------------------

    async def _normalize(self, field: str, value: str | None) -> str | None:
        """Run the validation-agent hook (free text - normalization only)."""
        if value is None:
            return None
        outcome = await self._validator.validate(field, value)
        if not outcome.is_valid:  # passthrough agent never trips this
            raise DomainValidationError(field, outcome.reason or "invalid value")
        return outcome.canonical or None
