"""Read-only integration with the Rachio Smart Irrigation Public API.

Zones and devices are the grower's real Rachio configuration. Our system only
*reads* them - all zone/device settings (names, vegetation, soil, nozzles,
slope, sun exposure) are edited in the official Rachio app. The single write
this service performs is :meth:`RachioService.start_zone_watering`, a manual
run the Foreman agent can trigger for a JIT irrigation task.

Docs: https://rachio.readme.io/reference  ·  limit: 1,700 calls/day per key,
so ``get_devices_and_zones`` is cached for 10 minutes.
"""
from __future__ import annotations

import time
from functools import lru_cache
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from ..config import Settings
from ..core.logging import get_logger
from .exceptions import NotFoundError, RachioError, RachioNotConfigured

_log = get_logger("app.rachio")

# indirection so tests can advance the cache clock
_monotonic = time.monotonic

_CACHE_TTL = 600.0          # seconds
_MIN_DURATION = 1          # Rachio rejects < 1s
_MAX_DURATION = 10_800     # ... and > 3h


class RachioZone(BaseModel):
    """A subset of the Rachio zone object. ``extra="allow"`` keeps every raw
    field so the detail view can surface anything Rachio adds."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: str
    name: str
    enabled: bool = True
    zone_number: int = Field(default=0, alias="zoneNumber")
    custom_nozzle: dict[str, Any] | None = Field(default=None, alias="customNozzle")
    custom_soil: dict[str, Any] | None = Field(default=None, alias="customSoil")
    custom_slope: dict[str, Any] | None = Field(default=None, alias="customSlope")
    custom_crop: dict[str, Any] | None = Field(default=None, alias="customCrop")
    custom_shade: dict[str, Any] | None = Field(default=None, alias="customShade")


class RachioDevice(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: str
    name: str
    status: str = "UNKNOWN"
    model: str | None = None
    zones: list[RachioZone] = Field(default_factory=list)


class RachioService:
    """One long-lived ``httpx.AsyncClient`` + a 10-minute device/zone cache."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: httpx.AsyncClient | None = None
        self._person_id: str | None = None
        self._devices: list[RachioDevice] | None = None
        self._fetched_at: float = 0.0

    # -- internals ------------------------------------------------------

    def _require_client(self) -> httpx.AsyncClient:
        if not self._settings.rachio_enabled:
            raise RachioNotConfigured
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._settings.rachio_base_url.rstrip("/"),
                headers={
                    "Authorization": f"Bearer {self._settings.rachio_api_key}",
                    "Content-Type": "application/json",
                },
                timeout=10.0,
            )
        return self._client

    async def _request(self, method: str, path: str, **kw: Any) -> httpx.Response:
        client = self._require_client()
        try:
            resp = await client.request(method, path, **kw)
            resp.raise_for_status()
            return resp
        except httpx.HTTPStatusError as exc:
            _log.warning(
                "rachio.http_error", method=method, path=path,
                status=exc.response.status_code,
            )
            raise RachioError(
                f"Rachio API {exc.response.status_code} for {method} {path}"
            ) from exc
        except httpx.RequestError as exc:
            _log.warning("rachio.request_error", method=method, path=path, error=str(exc))
            raise RachioError(f"Could not reach the Rachio API: {exc}") from exc

    # -- reads ---------------------------------------------------------

    async def get_person_info(self) -> str:
        """The account's person id (``GET /person/info``); memoised for the
        lifetime of the service - it never changes."""
        if self._person_id is None:
            data = (await self._request("GET", "/person/info")).json()
            self._person_id = str(data["id"])
        return self._person_id

    async def get_devices_and_zones(self, *, refresh: bool = False) -> list[RachioDevice]:
        """Every device with its nested zones (``GET /person/{id}``), cached for
        :data:`_CACHE_TTL` seconds to stay well within Rachio's daily limit."""
        fresh = self._devices is not None and (_monotonic() - self._fetched_at) < _CACHE_TTL
        if fresh and not refresh:
            return self._devices  # type: ignore[return-value]

        person_id = await self.get_person_info()
        data = (await self._request("GET", f"/person/{person_id}")).json()
        devices = [RachioDevice.model_validate(d) for d in data.get("devices", [])]
        for device in devices:  # Rachio returns zones unordered
            device.zones.sort(key=lambda z: z.zone_number)
        self._devices = devices
        self._fetched_at = _monotonic()
        _log.info(
            "rachio.devices.fetched",
            devices=len(self._devices),
            zones=sum(len(d.zones) for d in self._devices),
        )
        return self._devices

    async def get_zone(self, zone_id: str) -> tuple[RachioDevice, RachioZone]:
        """Resolve one zone (and its device) from the cache. 404 if unknown."""
        for device in await self.get_devices_and_zones():
            for zone in device.zones:
                if zone.id == zone_id:
                    return device, zone
        raise NotFoundError(f"Rachio zone {zone_id!r} not found on this account")

    # -- the one allowed write --------------------------------------

    async def start_zone_watering(self, zone_id: str, duration_seconds: int) -> None:
        """Start a manual watering run on one zone (``PUT /zone/start``).

        This turns on real hardware. ``duration_seconds`` is clamped to
        Rachio's 1..10800s range.
        """
        duration = max(_MIN_DURATION, min(int(duration_seconds), _MAX_DURATION))
        await self._request(
            "PUT", "/zone/start", json={"id": zone_id, "duration": duration}
        )
        _log.info("rachio.zone.started", zone_id=zone_id, duration_seconds=duration)

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


@lru_cache
def get_rachio_service(settings: Settings) -> RachioService:
    """Process-wide singleton per ``Settings`` (holds a pooled AsyncClient +
    the device cache). Mirrors ``get_vector_store``."""
    return RachioService(settings)
