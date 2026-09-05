"""Local zone overlay: grower labels and in-use flags on Rachio zones.

Display rule: grower ``label`` if set, otherwise ``Zone {rachio zone_number}``,
otherwise ``Zone {zone_id}``. Unused zones stay in the unused list on /zones
and are omitted from planning, pickers, and supervision.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..config import Settings
from ..repositories.zone_repository import ZoneRepository
from ..schemas.irrigation import (
    IrrigationOverview,
    SensorSnapshot,
    SensorZoneRead,
    SupervisorProposal,
    SupervisorRunResult,
    ZoneConfig,
)
from ..schemas.tree import TreeRead
from ..schemas.zone import ZoneInUseRead, ZoneLabelRead
from .exceptions import RachioError, RachioNotConfigured
from .rachio import RachioDevice, RachioZone, get_rachio_service


def zone_display_name(
    label: str | None,
    zone_number: int | None,
    zone_id: str,
) -> str:
    text = (label or "").strip()
    if text:
        return text
    if zone_number:
        return f"Zone {zone_number}"
    return f"Zone {zone_id}"


@dataclass(frozen=True)
class ZoneCatalog:
    labels: dict[str, str]
    numbers: dict[str, int]
    unused: set[str]

    def label_for(self, zone_id: str) -> str | None:
        return self.labels.get(zone_id)

    def number_for(self, zone_id: str) -> int | None:
        n = self.numbers.get(zone_id)
        return n if n else None

    def in_use(self, zone_id: str) -> bool:
        return zone_id not in self.unused

    def display(self, zone_id: str) -> str:
        return zone_display_name(
            self.label_for(zone_id), self.number_for(zone_id), zone_id
        )


class ZoneService:
    def __init__(self, zones: ZoneRepository, settings: Settings) -> None:
        self._zones = zones
        self._settings = settings
        self._catalog: ZoneCatalog | None = None

    async def catalog(self) -> ZoneCatalog:
        if self._catalog is None:
            self._catalog = ZoneCatalog(
                labels=await self._zones.all_labels(),
                numbers=await self._rachio_numbers(),
                unused=await self._zones.unused_ids(),
            )
        return self._catalog

    async def set_label(self, zone_id: str, label: str | None) -> ZoneLabelRead:
        cleaned = (label or "").strip() or None
        await self._zones.upsert(zone_id, cleaned)
        self._catalog = None
        cat = await self.catalog()
        return ZoneLabelRead(
            zone_id=zone_id,
            label=cat.label_for(zone_id),
            display_name=cat.display(zone_id),
            zone_number=cat.number_for(zone_id),
            in_use=cat.in_use(zone_id),
        )

    async def set_in_use(self, zone_id: str, in_use: bool) -> ZoneInUseRead:
        await self._zones.set_in_use(zone_id, in_use)
        self._catalog = None
        cat = await self.catalog()
        return ZoneInUseRead(
            zone_id=zone_id,
            in_use=cat.in_use(zone_id),
            label=cat.label_for(zone_id),
            display_name=cat.display(zone_id),
            zone_number=cat.number_for(zone_id),
        )

    async def unused_ids(self) -> set[str]:
        return (await self.catalog()).unused

    async def overlay_devices(self, devices: list[RachioDevice]) -> list[RachioDevice]:
        labels = await self._zones.all_labels()
        unused = await self._zones.unused_ids()
        return [_overlay_device(d, labels, unused) for d in devices]

    async def overlay_zone(self, zone: RachioZone) -> RachioZone:
        labels = await self._zones.all_labels()
        unused = await self._zones.unused_ids()
        return _overlay_rachio_zone(zone, labels, unused)

    async def enrich_trees(self, trees: list[TreeRead]) -> list[TreeRead]:
        cat = await self.catalog()
        return [_enrich_tree(t, cat) for t in trees]

    async def enrich_tree(self, tree: TreeRead) -> TreeRead:
        return (await self.enrich_trees([tree]))[0]

    async def enrich_zone_config(self, zone: ZoneConfig) -> ZoneConfig:
        cat = await self.catalog()
        return _enrich_zone_config(zone, cat)

    async def enrich_overview(self, overview: IrrigationOverview) -> IrrigationOverview:
        cat = await self.catalog()
        return overview.model_copy(
            update={
                "zones": [
                    _enrich_zone_config(z, cat)
                    for z in overview.zones
                    if cat.in_use(z.zone_id)
                ]
            }
        )

    async def enrich_snapshot(self, snap: SensorSnapshot) -> SensorSnapshot:
        cat = await self.catalog()
        return snap.model_copy(
            update={
                "zones": [
                    _enrich_sensor_zone(z, cat)
                    for z in snap.zones
                    if cat.in_use(z.zone_id)
                ]
            }
        )

    async def enrich_proposal(self, proposal: SupervisorProposal) -> SupervisorProposal:
        cat = await self.catalog()
        return _enrich_proposal(proposal, cat)

    async def enrich_proposals(
        self, proposals: list[SupervisorProposal]
    ) -> list[SupervisorProposal]:
        cat = await self.catalog()
        return [_enrich_proposal(p, cat) for p in proposals]

    async def enrich_run(self, result: SupervisorRunResult) -> SupervisorRunResult:
        cat = await self.catalog()
        return result.model_copy(
            update={"proposals": [_enrich_proposal(p, cat) for p in result.proposals]}
        )

    async def _rachio_numbers(self) -> dict[str, int]:
        try:
            devices = await get_rachio_service(self._settings).get_devices_and_zones()
        except (RachioNotConfigured, RachioError):
            return {}
        return {z.id: z.zone_number for d in devices for z in d.zones if z.zone_number}


def _overlay_rachio_zone(
    zone: RachioZone, labels: dict[str, str], unused: set[str]
) -> RachioZone:
    label = labels.get(zone.id)
    return zone.model_copy(
        update={
            "label": label,
            "display_name": zone_display_name(label, zone.zone_number, zone.id),
            "in_use": zone.id not in unused,
        }
    )


def _overlay_device(
    device: RachioDevice, labels: dict[str, str], unused: set[str]
) -> RachioDevice:
    return device.model_copy(
        update={"zones": [_overlay_rachio_zone(z, labels, unused) for z in device.zones]}
    )


def _enrich_tree(tree: TreeRead, cat: ZoneCatalog) -> TreeRead:
    if not tree.zone_id:
        return tree
    return tree.model_copy(
        update={
            "zone_label": cat.label_for(tree.zone_id),
            "zone_display_name": cat.display(tree.zone_id),
        }
    )


def _enrich_zone_config(zone: ZoneConfig, cat: ZoneCatalog) -> ZoneConfig:
    return zone.model_copy(
        update={
            "label": cat.label_for(zone.zone_id),
            "display_name": cat.display(zone.zone_id),
            "zone_number": cat.number_for(zone.zone_id),
        }
    )


def _enrich_sensor_zone(zone: SensorZoneRead, cat: ZoneCatalog) -> SensorZoneRead:
    return zone.model_copy(
        update={
            "label": cat.label_for(zone.zone_id),
            "display_name": cat.display(zone.zone_id),
            "zone_number": cat.number_for(zone.zone_id),
        }
    )


def _enrich_proposal(proposal: SupervisorProposal, cat: ZoneCatalog) -> SupervisorProposal:
    return proposal.model_copy(
        update={
            "label": cat.label_for(proposal.zone_id),
            "display_name": cat.display(proposal.zone_id),
            "zone_number": cat.number_for(proposal.zone_id),
        }
    )
