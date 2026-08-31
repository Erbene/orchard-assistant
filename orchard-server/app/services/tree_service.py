"""Tree business logic: free-text canonicalization, referential checks,
and derived age. HTTP-agnostic; returns Pydantic models."""
from __future__ import annotations

import sqlite3
from datetime import date

from ..repositories.tree_repository import TreeRepository
from ..repositories.zone_repository import ZoneRepository
from ..schemas.tree import TreeCreate, TreeRead, TreeUpdate
from .exceptions import ConflictError, DomainValidationError, NotFoundError
from .validators import ValidationAgent


def derive_age(planted_date: str | None) -> tuple[int | None, float | None]:
    """Age from an ISO date string. Never stored - computed on every read."""
    if not planted_date:
        return None, None
    try:
        planted = date.fromisoformat(planted_date)
    except ValueError:
        return None, None
    days = (date.today() - planted).days
    return days, round(days / 365.25, 2)


class TreeService:
    def __init__(
        self,
        trees: TreeRepository,
        zones: ZoneRepository,
        validator: ValidationAgent,
    ) -> None:
        self._trees = trees
        self._zones = zones
        self._validator = validator

    async def list_trees(
        self, *, species: str | None = None, zone_id: str | None = None
    ) -> list[TreeRead]:
        rows = self._trees.list(species=species, zone_id=zone_id)
        return [self._to_read(r) for r in rows]

    async def get_tree(self, tree_id: int) -> TreeRead:
        row = self._trees.get(tree_id)
        if row is None:
            raise NotFoundError(f"tree {tree_id} not found")
        return self._to_read(row)

    async def create_tree(self, payload: TreeCreate) -> TreeRead:
        record = {
            "tree_id": payload.tree_id,
            "species": await self._require_canonical("species", payload.species),
            "variety": await self._require_canonical("variety", payload.variety),
            "zone_id": await self._check_zone(payload.zone_id),
            "planted_date": payload.planted_date.isoformat() if payload.planted_date else None,
            "additional_context": payload.additional_context,
            "notes": payload.notes,
        }
        try:
            row = self._trees.create(record)
        except sqlite3.IntegrityError as exc:
            raise ConflictError(f"tree {payload.tree_id} already exists") from exc
        return self._to_read(row)

    async def update_tree(self, tree_id: int, payload: TreeUpdate) -> TreeRead:
        if self._trees.get(tree_id) is None:
            raise NotFoundError(f"tree {tree_id} not found")

        patch = payload.model_dump(exclude_unset=True)
        if "species" in patch:
            patch["species"] = await self._require_canonical("species", patch["species"])
        if "variety" in patch:
            patch["variety"] = await self._require_canonical("variety", patch["variety"])
        if "zone_id" in patch:
            patch["zone_id"] = await self._check_zone(patch["zone_id"])
        if "planted_date" in patch and patch["planted_date"] is not None:
            patch["planted_date"] = patch["planted_date"].isoformat()

        row = self._trees.update(tree_id, patch)
        return self._to_read(row)

    async def delete_tree(self, tree_id: int) -> None:
        if not self._trees.delete(tree_id):
            raise NotFoundError(f"tree {tree_id} not found")

    # -- helpers -------------------------------------------------------

    async def _require_canonical(self, field: str, value: str) -> str:
        outcome = await self._validator.validate(field, value)
        if not outcome.is_valid:
            raise DomainValidationError(field, outcome.reason or "invalid value")
        return outcome.canonical

    async def _check_zone(self, zone_id: str | None) -> str | None:
        if zone_id is None:
            return None
        if not self._zones.exists(zone_id):
            raise DomainValidationError("zone_id", f"zone {zone_id!r} does not exist")
        return zone_id

    @staticmethod
    def _to_read(row: dict) -> TreeRead:
        age_days, age_years = derive_age(row.get("planted_date"))
        return TreeRead.model_validate({**row, "age_days": age_days, "age_years": age_years})
