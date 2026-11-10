"""Helpers for turning stored readings into API values, shared by the routers."""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

import aiosqlite

_COMPASS_POINTS = (
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
)  # fmt: skip


def as_utc(value: datetime) -> datetime:
    """Naive datetimes are taken to be UTC; aware ones are converted to it.

    Stored timestamps are UTC ISO strings and are compared as text, so every
    bound has to be UTC too or a client sending "+10:00" gets a window
    silently shifted by ten hours (and mixing naive with aware raises).
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def round_or_none(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


def adjust_rain(value: float | None, baseline: float | None) -> float | None:
    """Shift the reset-aware rain total to be relative to a baseline, clamped
    so float noise can't show it going negative.
    """
    if value is None or baseline is None:
        return value
    return max(value - baseline, 0.0)


def rain_total(decoded: dict[str, Any]) -> float | None:
    """rain_total_mm is the reset-aware running total (see RainTracker);
    readings stored before that field existed fall back to the sensor's raw
    cumulative value, which is equivalent since no reset had happened yet.
    """
    total = decoded.get("rain_total_mm")
    return total if total is not None else decoded.get("rain_mm")


def compass_point(degrees: float) -> str:
    return _COMPASS_POINTS[round(degrees / 22.5) % 16]


def wind_direction(sin_mean: float | None, cos_mean: float | None) -> tuple[float | None, str | None]:
    """The prevailing direction from the mean of the readings' sines and
    cosines. A plain average of degrees is wrong around north: 350° and 10°
    average to 180°, due south, when the wind was blowing from the north.
    """
    if sin_mean is None or cos_mean is None or math.hypot(sin_mean, cos_mean) < 1e-9:
        return None, None
    degrees = math.degrees(math.atan2(sin_mean, cos_mean)) % 360
    return float(round(degrees) % 360), compass_point(degrees)


def dew_point_c(temperature_c: float, humidity: float) -> float | None:
    """Magnus formula. The temperature the air would have to cool to for
    its moisture to start condensing: the higher it is, the muggier it feels."""
    if humidity <= 0:
        return None
    b, c = 17.62, 243.12
    gamma = math.log(humidity / 100.0) + b * temperature_c / (c + temperature_c)
    return c * gamma / (b - gamma)


def feels_like_c(temperature_c: float, humidity: float, wind_km_h: float) -> float:
    """Apparent temperature as the Australian Bureau of Meteorology computes
    it (Steadman, without a solar term): humidity makes it feel warmer, wind
    cooler. Their formula assumes wind at 10 m, and a garden sensor sits
    lower, so on a breezy day this reads a touch warm."""
    vapour_pressure = humidity / 100.0 * 6.105 * math.exp(17.27 * temperature_c / (237.7 + temperature_c))
    return temperature_c + 0.33 * vapour_pressure - 0.70 * (wind_km_h / 3.6) - 4.00


def counts_outage_rain(hours: float) -> bool:
    """Whether a look-back window of this length counts rain from before its
    first reading. Rain that fell while the station was offline arrives as
    one jump on the first reading back: longer windows count it so it isn't
    lost, but the last hour or less doesn't, since that would say it fell
    just now."""
    return hours > 1


def bucket_rain(rows: Sequence[aiosqlite.Row], carry_in: float | None = None) -> list[float | None]:
    """Rain that fell in each bucket. The total is cumulative, so a bucket's
    rain is how far the total rose since the end of the previous bucket
    (carried across empty buckets, so overnight rain between two sparse
    readings still lands somewhere). The first bucket starts from `carry_in`,
    the total at the last reading before the window, or from its own spread
    when there isn't one.
    """
    rain: list[float | None] = []
    previous_high: float | None = carry_in
    for row in rows:
        high = row["rain_max_mm"]
        if high is None:
            rain.append(None)
            continue
        low = previous_high if previous_high is not None else row["rain_min_mm"]
        rain.append(round(max(high - low, 0.0), 2))
        previous_high = high
    return rain
