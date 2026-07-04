from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

_TIMESTAMP_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S")

# 433MHz is unlicensed and unauthenticated: any transmitter in range (a
# neighbor's sensor, a car remote, a garage door, deliberately crafted noise)
# can produce a plausible-looking JSON line. These bounds are generous
# physical limits, not calibration targets, so real weather never trips them.
_FIELD_BOUNDS: dict[str, tuple[float, float]] = {
    "temperature_c": (-50.0, 60.0),
    "humidity": (0.0, 100.0),
    "wind_dir_deg": (0.0, 360.0),
    "wind_avg_km_h": (0.0, 250.0),
    "wind_max_km_h": (0.0, 250.0),
    "rain_mm": (0.0, 100_000.0),
}


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


def _is_valid_number(value: Any) -> bool:
    # bool is a subclass of int in Python, so isinstance(True, int) is True;
    # excluded explicitly since a spoofed "humidity": true must not read as 1.
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def sanitize_decoded(decoded: dict[str, Any]) -> dict[str, Any]:
    """Null out any field that's wrongly typed, non-finite, or outside a
    physically plausible range instead of discarding the whole reading —
    a single corrupted field shouldn't cost the rest of an otherwise-good
    reading.
    """
    for field, (low, high) in _FIELD_BOUNDS.items():
        value = decoded.get(field)
        if value is not None and not (_is_valid_number(value) and low <= value <= high):
            decoded[field] = None

    battery_ok = decoded.get("battery_ok")
    if battery_ok is not None and battery_ok not in (0, 1):
        decoded["battery_ok"] = None

    return decoded


def matches_expected_sensor(payload: dict[str, Any], model_filter: str, id_filter: int | None) -> bool:
    """Reject readings from any device that isn't the configured sensor, so a
    neighbor's weather station or an unrelated 433MHz gadget in range can't
    get mixed into this station's history.
    """
    model = payload.get("model")
    if not isinstance(model, str) or model_filter.lower() not in model.lower():
        return False
    if id_filter is not None and payload.get("id") != id_filter:
        return False
    return True


_RAIN_RESET_EPSILON = 1e-6


def compute_rain_total_mm(
    current_raw_mm: float | None,
    previous_raw_mm: float | None,
    previous_total_mm: float | None,
) -> float | None:
    """Fold the sensor's cumulative rain counter into a total that survives
    counter resets (e.g. new batteries make the sensor restart counting from
    zero). Whenever the raw value drops instead of climbing, that drop is
    treated as a reset and the prior total is carried forward rather than
    letting the displayed total fall back down.
    """
    if current_raw_mm is None:
        return None
    if previous_raw_mm is None or previous_total_mm is None:
        return current_raw_mm
    if current_raw_mm + _RAIN_RESET_EPSILON < previous_raw_mm:
        return previous_total_mm + current_raw_mm
    return previous_total_mm + (current_raw_mm - previous_raw_mm)


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
