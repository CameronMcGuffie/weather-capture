from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
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


_RAIN_EPSILON = 1e-6

# Rain between two consecutive readings is a fraction of a millimetre, and
# even an hours-long outage in a downpour stays far below this. A bigger
# step is treated as suspect until the next reading backs it up. It also
# bounds the damage of a glitch the tracker can't tell apart from rain: a
# bogus reading this much higher than the truth is accepted as rain once.
_RAIN_MAX_STEP_MM = 50.0


def _is_plausible_rain_step(step: float) -> bool:
    return -_RAIN_EPSILON <= step <= _RAIN_MAX_STEP_MM


class RainTracker:
    """Folds the sensor's cumulative rain counter into a running total that
    survives counter resets (new batteries restart the sensor from zero).

    The counter only ever climbs, so a big drop means a reset and the total
    carries on from where it was. But 433MHz is unauthenticated, so a single
    corrupt or spoofed reading can look just like a reset: acting on it
    immediately would add the whole bogus value, and the real reading right
    after would add it again (a 12.3mm glitch between two 408.6mm readings
    doubled the total). So an implausible reading is held back, and only
    counts once the next reading agrees with it; if the next reading goes
    back to normal, the held one is discarded as a glitch.

    A small drop (under the step limit) is never a reset, since a reset
    restarts the counter near zero. It means the reading before was a high
    glitch, so the tracker re-bases onto the lower value without adding it.
    """

    def __init__(self, raw_mm: float | None = None, total_mm: float | None = None) -> None:
        self._raw_mm = raw_mm
        self._total_mm = total_mm
        self._suspect_mm: float | None = None

    def update(self, raw_mm: float | None) -> tuple[float | None, bool]:
        """Returns (running total, whether this raw reading was accepted).

        A reading that isn't accepted is held pending confirmation; the
        total stays where it was.
        """
        if raw_mm is None:
            return None, True

        if self._raw_mm is None or self._total_mm is None:
            self._raw_mm = raw_mm
            self._total_mm = raw_mm
            return raw_mm, True

        step = raw_mm - self._raw_mm
        if _is_plausible_rain_step(step):
            self._total_mm += max(step, 0.0)
            self._raw_mm = raw_mm
            self._suspect_mm = None
            return self._total_mm, True

        suspect = self._suspect_mm
        if suspect is not None and suspect - _RAIN_EPSILON <= raw_mm <= suspect + _RAIN_MAX_STEP_MM:
            # Two readings in a row agree on the new level, so it's real.
            if step > 0:
                self._total_mm += step  # a genuinely big gain
            elif -step > _RAIN_MAX_STEP_MM:
                self._total_mm += raw_mm  # a reset: the counter now counts from zero again
            # else: a small drop, so the previous reading was the outlier
            self._raw_mm = raw_mm
            self._suspect_mm = None
            return self._total_mm, True

        self._suspect_mm = raw_mm
        return self._total_mm, False


@dataclass
class RainRepair:
    totals: list[float | None]
    glitch_readings: int
    # (index of the first reading involved, what happened, the raw value there)
    events: list[tuple[int, str, float]]


def repair_rain_totals(raw_mm: Sequence[float | None]) -> RainRepair:
    """Recompute the running rain total for a whole stored history, with
    hindsight.

    RainTracker has to decide about a suspicious reading having seen only
    the one after it. Over stored history the whole series is known, which
    allows a stronger rule: the counter only climbs, so if it later comes
    back to the level it left (however long it was away), whatever it did
    in between was noise and is skipped. A real reset can't do that, since
    getting back to the old level would take as much rain again.
    """
    totals: list[float | None] = [None] * len(raw_mm)
    events: list[tuple[int, str, float]] = []
    readings = [(index, value) for index, value in enumerate(raw_mm) if value is not None]
    if not readings:
        return RainRepair(totals, 0, events)

    # Split into runs of readings that each follow plausibly from the last.
    runs: list[list[tuple[int, float]]] = []
    for reading in readings:
        if runs and _is_plausible_rain_step(reading[1] - runs[-1][-1][1]):
            runs[-1].append(reading)
        else:
            runs.append([reading])

    total = 0.0
    last_good: float | None = None
    glitch_readings = 0
    position = 0
    while position < len(runs):
        run = runs[position]
        first_index, first_value = run[0]

        # Only a run that breaks away from the last good level can be noise;
        # one that carries on from it plausibly is just the series continuing.
        if last_good is not None and not _is_plausible_rain_step(first_value - last_good):
            rejoin = next(
                (
                    later
                    for later in range(position + 1, len(runs))
                    if _is_plausible_rain_step(runs[later][0][1] - last_good)
                ),
                None,
            )
            if rejoin is not None:
                for skipped in runs[position:rejoin]:
                    for index, _ in skipped:
                        totals[index] = total
                        glitch_readings += 1
                events.append((first_index, "glitch", first_value))
                position = rejoin
                continue

        if last_good is None:
            total = first_value
        else:
            step = first_value - last_good
            if _is_plausible_rain_step(step):
                total += max(step, 0.0)
            elif step > 0:
                total += step
                events.append((first_index, "big_gain", first_value))
            elif -step > _RAIN_MAX_STEP_MM:
                total += first_value
                events.append((first_index, "reset", first_value))
            else:
                events.append((first_index, "rebase", first_value))
        totals[first_index] = total
        previous = first_value
        for index, value in run[1:]:
            total += max(value - previous, 0.0)
            previous = value
            totals[index] = total
        last_good = previous
        position += 1

    return RainRepair(totals, glitch_readings, events)


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
