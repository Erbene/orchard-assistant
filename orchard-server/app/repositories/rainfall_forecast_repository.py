"""Raw persistence for ``rainfall_forecast_log`` (Irrigation Phase 1).

One row per calendar day, keyed by ``for_date``. The roll job upserts the
forecast columns ahead of time and the actual columns the day after.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

Row = dict[str, Any]

_SETTABLE = frozenset(
    {
        "forecast_1d_mm", "forecast_3d_mm", "forecast_5d_mm",
        "forecast_1d_at", "forecast_3d_at", "forecast_5d_at",
        "actual_nws_mm", "actual_gauge_mm", "actuals_at",
    }
)


class RainfallForecastRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def get(self, for_date: date) -> Row | None:
        result = await self._conn.execute(
            text("SELECT * FROM rainfall_forecast_log WHERE for_date = :d"),
            {"d": for_date},
        )
        row = result.mappings().first()
        return dict(row) if row is not None else None

    async def upsert(self, for_date: date, fields: Row) -> Row:
        cols = [c for c in fields if c in _SETTABLE]
        if not cols:
            return await self.get(for_date) or {"for_date": for_date}
        insert_cols = ["for_date", *cols]
        placeholders = ", ".join(f":{c}" for c in insert_cols)
        updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols)
        result = await self._conn.execute(
            text(
                f"INSERT INTO rainfall_forecast_log ({', '.join(insert_cols)})"
                f" VALUES ({placeholders})"
                f" ON CONFLICT (for_date) DO UPDATE SET {updates}, updated_at = now()"
                " RETURNING *"
            ),
            {"for_date": for_date, **{c: fields[c] for c in cols}},
        )
        return dict(result.mappings().one())

    async def range(self, start: date, end: date) -> list[Row]:
        result = await self._conn.execute(
            text(
                "SELECT * FROM rainfall_forecast_log"
                " WHERE for_date BETWEEN :s AND :e ORDER BY for_date"
            ),
            {"s": start, "e": end},
        )
        return [dict(r) for r in result.mappings().all()]
