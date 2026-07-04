from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

_TIMESTAMP_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S")


def decode_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize a raw rtl_433 Fine Offset reading into a canonical field set.

    rtl_433 reports wind speed in m/s; the dashboard and aggregation queries
    work in km/h, so both units are derived here rather than at read time.
    """
    decoded = dict(payload)

    wind_avg_m_s = payload.get("wind_avg_m_s")
    if isinstance(wind_avg_m_s, (int, float)):
        decoded.setdefault("wind_avg_km_h", round(wind_avg_m_s * 3.6, 2))

    wind_max_m_s = payload.get("wind_max_m_s")
    if isinstance(wind_max_m_s, (int, float)):
        decoded.setdefault("wind_max_km_h", round(wind_max_m_s * 3.6, 2))

    if "temperature_c" not in decoded and "temperature_C" in decoded:
        decoded["temperature_c"] = decoded["temperature_C"]

    return decoded


def parse_payload_timestamp(payload: dict[str, Any]) -> datetime:
    raw_time = payload.get("time")
    if isinstance(raw_time, str):
        for fmt in _TIMESTAMP_FORMATS:
            try:
                # rtl_433's default "time" field is the host's local time, not UTC
                # (no -M utc flag is used); .astimezone() on a naive datetime
                # interprets it in the system timezone before converting.
                naive_local = datetime.strptime(raw_time, fmt)
                return naive_local.astimezone(timezone.utc)
            except ValueError:
                continue
    return datetime.now(timezone.utc)
