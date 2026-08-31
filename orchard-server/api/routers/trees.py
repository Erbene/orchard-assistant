"""CRUD endpoints for trees."""
from __future__ import annotations

import sqlite3
from datetime import date

from fastapi import APIRouter, HTTPException, Query, status

from ..db import get_conn
from ..models import Tree, TreeCreate, TreeUpdate

router = APIRouter(prefix="/trees", tags=["trees"])


def _derive_age(planted_date: str | None) -> tuple[int | None, float | None]:
    if not planted_date:
        return None, None
    try:
        planted = date.fromisoformat(planted_date)
    except ValueError:
        return None, None
    days = (date.today() - planted).days
    return days, round(days / 365.25, 2)


def _row_to_tree(row: sqlite3.Row) -> Tree:
    age_days, age_years = _derive_age(row["planted_date"])
    return Tree(
        tree_id=row["tree_id"],
        species=row["species"],
        variety=row["variety"],
        zone_id=row["zone_id"],
        planted_date=row["planted_date"],
        additional_context=row["additional_context"],
        notes=row["notes"],
        age_days=age_days,
        age_years=age_years,
    )


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _assert_zone_exists(conn: sqlite3.Connection, zone_id: str | None) -> None:
    if zone_id is None:
        return
    if conn.execute("SELECT 1 FROM zone WHERE zone_id = ?", (zone_id,)).fetchone() is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"zone {zone_id!r} does not exist"
        )


@router.get("", response_model=list[Tree])
def list_trees(
    species: str | None = Query(default=None),
    zone_id: str | None = Query(default=None),
) -> list[Tree]:
    clauses: list[str] = []
    params: list[object] = []
    if species is not None:
        clauses.append("species = ?")
        params.append(species)
    if zone_id is not None:
        clauses.append("zone_id = ?")
        params.append(zone_id)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM tree{where} ORDER BY tree_id", params
        ).fetchall()
    return [_row_to_tree(r) for r in rows]


@router.get("/{tree_id}", response_model=Tree)
def get_tree(tree_id: int) -> Tree:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM tree WHERE tree_id = ?", (tree_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"tree {tree_id} not found")
    return _row_to_tree(row)


@router.post("", response_model=Tree, status_code=status.HTTP_201_CREATED)
def create_tree(payload: TreeCreate) -> Tree:
    with get_conn() as conn:
        _assert_zone_exists(conn, payload.zone_id)
        columns = ["species", "variety", "zone_id", "planted_date",
                   "additional_context", "notes"]
        values: list[object] = [
            payload.species.value,
            payload.variety,
            payload.zone_id,
            _iso(payload.planted_date),
            payload.additional_context,
            payload.notes,
        ]
        if payload.tree_id is not None:
            columns.insert(0, "tree_id")
            values.insert(0, payload.tree_id)
        placeholders = ", ".join("?" for _ in columns)
        try:
            cur = conn.execute(
                f"INSERT INTO tree ({', '.join(columns)}) VALUES ({placeholders})",
                values,
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"tree {payload.tree_id} already exists",
            ) from exc
        new_id = payload.tree_id if payload.tree_id is not None else cur.lastrowid
        row = conn.execute(
            "SELECT * FROM tree WHERE tree_id = ?", (new_id,)
        ).fetchone()
    return _row_to_tree(row)


@router.patch("/{tree_id}", response_model=Tree)
def update_tree(tree_id: int, payload: TreeUpdate) -> Tree:
    fields = payload.model_dump(exclude_unset=True)
    with get_conn() as conn:
        exists = conn.execute(
            "SELECT 1 FROM tree WHERE tree_id = ?", (tree_id,)
        ).fetchone()
        if exists is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"tree {tree_id} not found")

        if "zone_id" in fields:
            _assert_zone_exists(conn, fields["zone_id"])

        if fields:
            sets: list[str] = []
            values: list[object] = []
            for key, value in fields.items():
                sets.append(f"{key} = ?")
                if hasattr(value, "value"):
                    values.append(value.value)
                elif isinstance(value, date):
                    values.append(value.isoformat())
                else:
                    values.append(value)
            values.append(tree_id)
            conn.execute(
                f"UPDATE tree SET {', '.join(sets)} WHERE tree_id = ?", values
            )

        row = conn.execute(
            "SELECT * FROM tree WHERE tree_id = ?", (tree_id,)
        ).fetchone()
    return _row_to_tree(row)


@router.delete(
    "/{tree_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None
)
def delete_tree(tree_id: int) -> None:
    with get_conn() as conn:
        exists = conn.execute(
            "SELECT 1 FROM tree WHERE tree_id = ?", (tree_id,)
        ).fetchone()
        if exists is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"tree {tree_id} not found")
        conn.execute("DELETE FROM tree WHERE tree_id = ?", (tree_id,))
