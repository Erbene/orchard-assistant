"""Moisture-sensor map + effective-reading resolution.

A tree's effective moisture = the mean of its own sensors' readings, or - if
it has none - the mean of its Rachio zone's sensors. Readings come from
``app.irrigation.hardware`` (stubbed in Phase 1).
"""
from __future__ import annotations

from ..repositories.moisture_sensor_repository import MoistureSensorRepository
from ..repositories.tree_repository import TreeRepository
from ..schemas.irrigation import (
    MoistureSensorCreate,
    MoistureSensorRead,
    MoistureSensorUpdate,
    SensorReading,
    TreeMoisture,
)
from ..services.exceptions import ConflictError, DomainValidationError, NotFoundError
from . import hardware


class MoistureSensorService:
    def __init__(
        self, sensors: MoistureSensorRepository, trees: TreeRepository
    ) -> None:
        self._sensors = sensors
        self._trees = trees

    # -- CRUD ---------------------------------------------------

    async def list(self) -> list[MoistureSensorRead]:
        return [MoistureSensorRead.model_validate(r) for r in await self._sensors.list()]

    async def get(self, sensor_id: str) -> MoistureSensorRead:
        row = await self._sensors.get(sensor_id)
        if row is None:
            raise NotFoundError(f"moisture sensor {sensor_id!r} not found")
        return MoistureSensorRead.model_validate(row)

    async def create(self, payload: MoistureSensorCreate) -> MoistureSensorRead:
        if payload.tree_id is None and payload.zone_id is None:
            raise DomainValidationError(
                "tree_id", "a sensor must be attached to a tree, a zone, or both"
            )
        if payload.tree_id is not None and await self._trees.get(payload.tree_id) is None:
            raise DomainValidationError("tree_id", f"tree {payload.tree_id} does not exist")
        if await self._sensors.get(payload.id) is not None:
            raise ConflictError(f"sensor {payload.id!r} already exists")
        row = await self._sensors.create(payload.model_dump())
        return MoistureSensorRead.model_validate(row)

    async def update(
        self, sensor_id: str, payload: MoistureSensorUpdate
    ) -> MoistureSensorRead:
        if await self._sensors.get(sensor_id) is None:
            raise NotFoundError(f"moisture sensor {sensor_id!r} not found")
        patch = payload.model_dump(exclude_unset=True)
        if patch.get("tree_id") is not None and await self._trees.get(patch["tree_id"]) is None:
            raise DomainValidationError("tree_id", f"tree {patch['tree_id']} does not exist")
        return MoistureSensorRead.model_validate(
            await self._sensors.update(sensor_id, patch)
        )

    async def delete(self, sensor_id: str) -> None:
        if not await self._sensors.delete(sensor_id):
            raise NotFoundError(f"moisture sensor {sensor_id!r} not found")

    # -- readings ---------------------------------------------

    async def sensors_for_tree(self, tree_id: int) -> list[MoistureSensorRead]:
        return [
            MoistureSensorRead.model_validate(r)
            for r in await self._sensors.for_tree(tree_id)
        ]

    async def tree_moisture(self, tree_id: int) -> TreeMoisture:
        """Effective VWC for a tree: its own sensors, else its zone's."""
        tree = await self._trees.get(tree_id)
        if tree is None:
            raise NotFoundError(f"tree {tree_id} not found")

        rows = await self._sensors.for_tree(tree_id)
        resolved = "tree"
        if not rows and tree.get("zone_id"):
            rows = await self._sensors.for_zone(tree["zone_id"])
            resolved = "zone"
        if not rows:
            return TreeMoisture(tree_id=tree_id, readings=[], resolved_via="none")

        readings = [
            SensorReading(sensor_id=r["id"], vwc_pct=hardware.get_moisture(r["id"]))
            for r in rows
        ]
        mean = round(sum(x.vwc_pct for x in readings) / len(readings), 1)
        return TreeMoisture(
            tree_id=tree_id,
            readings=readings,
            mean_vwc_pct=mean,
            resolved_via=resolved,
        )

    async def ensure_for_tree(
        self, tree_id: int, *, sensor_id: str | None = None, label: str = "Demo pin"
    ) -> MoistureSensorRead:
        """Return the tree's first sensor, creating a demo pin if it has none."""
        existing = await self.sensors_for_tree(tree_id)
        if existing:
            return existing[0]
        tree = await self._trees.get(tree_id)
        if tree is None:
            raise NotFoundError(f"tree {tree_id} not found")
        sid = sensor_id or f"demo-{tree_id}"
        try:
            return await self.create(
                MoistureSensorCreate(
                    id=sid,
                    label=label,
                    tree_id=tree_id,
                    zone_id=tree.get("zone_id"),
                )
            )
        except ConflictError:
            return await self.get(sid)
