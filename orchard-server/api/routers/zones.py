"""CRUD endpoints for zones."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, HTTPException, status

from ..db import get_conn
from ..models import Zone, ZoneCreate, ZoneUpdate

router = APIRouter(prefix="/zones", tags=["zones"])


def _row_to_zone(row: sqlite3.Row) -> Zone:
    return Zone(
        zone_id=row["zone_id"],
        name=row["name"],
        soil_drainage=row["soil_drainage"],
    )


@router.get("", response_model=list[Zone])
def list_zones() -> list[Zone]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM zone ORDER BY zone_id").fetchall()
    return [_row_to_zone(r) for r in rows]


@router.get("/{zone_id}", response_model=Zone)
def get_zone(zone_id: str) -> Zone:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM zone WHERE zone_id = ?", (zone_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"zone {zone_id!r} not found")
    return _row_to_zone(row)


@router.post("", response_model=Zone, status_code=status.HTTP_201_CREATED)
def create_zone(payload: ZoneCreate) -> Zone:
    with get_conn() as conn:
        try:
            conn.execute(
                "INSERT INTO zone (zone_id, name, soil_drainage) VALUES (?, ?, ?)",
                (
                    payload.zone_id,
                    payload.name,
                    payload.soil_drainage.value if payload.soil_drainage else None,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"zone {payload.zone_id!r} already exists",
            ) from exc
        row = conn.execute(
            "SELECT * FROM zone WHERE zone_id = ?", (payload.zone_id,)
        ).fetchone()
    return _row_to_zone(row)


@router.patch("/{zone_id}", response_model=Zone)
def update_zone(zone_id: str, payload: ZoneUpdate) -> Zone:
    fields = payload.model_dump(exclude_unset=True)
    with get_conn() as conn:
        exists = conn.execute(
            "SELECT 1 FROM zone WHERE zone_id = ?", (zone_id,)
        ).fetchone()
        if exists is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"zone {zone_id!r} not found")

        if fields:
            sets = []
            values: list[object] = []
            for key, value in fields.items():
                sets.append(f"{key} = ?")
                values.append(value.value if hasattr(value, "value") else value)
            values.append(zone_id)
            conn.execute(f"UPDATE zone SET {', '.join(sets)} WHERE zone_id = ?", values)

        row = conn.execute(
            "SELECT * FROM zone WHERE zone_id = ?", (zone_id,)
        ).fetchone()
    return _row_to_zone(row)


@router.delete(
    "/{zone_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None
)
def delete_zone(zone_id: str) -> None:
    with get_conn() as conn:
        exists = conn.execute(
            "SELECT 1 FROM zone WHERE zone_id = ?", (zone_id,)
        ).fetchone()
        if exists is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"zone {zone_id!r} not found")
        try:
            conn.execute("DELETE FROM zone WHERE zone_id = ?", (zone_id,))
        except sqlite3.IntegrityError as exc:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"zone {zone_id!r} is still referenced by one or more trees",
            ) from exc
