"""Shared deficit arithmetic for water balance and the zone solver.

Forecast rain is discounted because quantitative precipitation forecasts are
often wrong; measured moisture and the rain gauge keep full weight.
"""
from __future__ import annotations

# How much of the next-24h QPF is credited against the deficit / post-VWC.
FORECAST_RAIN_WEIGHT = 0.3


def credited_forecast_mm(forecast_rain_24h_mm: float) -> float:
    return max(0.0, float(forecast_rain_24h_mm)) * FORECAST_RAIN_WEIGHT


def deficit_score(
    moisture_gap: float, rain_24h_mm: float, forecast_rain_24h_mm: float
) -> float:
    """Higher = drier. Moisture gap is VWC points; rain terms are mm."""
    return round(
        moisture_gap - rain_24h_mm - credited_forecast_mm(forecast_rain_24h_mm),
        1,
    )
