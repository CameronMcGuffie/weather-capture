"""Sunrise and sunset, for shading the night on the chart."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from astral import LocationInfo
from astral.sun import sun

SunKind = Literal["sunrise", "sunset"]

# The caller needs to know whether the window starts in daylight or dark, which
# means the event before the window's first one, so cover a margin either side.
_MARGIN = timedelta(hours=36)


def sun_events(latitude: float, longitude: float, start: datetime, end: datetime) -> list[tuple[datetime, SunKind]]:
    """Every sunrise and sunset from just before `start` to just after `end`, in order (UTC).

    Dates are walked a couple of days past each edge and the result trimmed,
    because the library files events under UTC dates: far east of Greenwich
    the sunrise that belongs to a local morning is dated the day before.
    """
    observer = LocationInfo(latitude=latitude, longitude=longitude).observer
    events: dict[datetime, SunKind] = {}
    day = (start - timedelta(days=2)).date()
    last = (end + timedelta(days=2)).date()
    while day <= last:
        try:
            times = sun(observer, date=day, tzinfo=timezone.utc)
        except ValueError:
            pass  # polar day or night: the sun doesn't rise or set on this date
        else:
            events[times["sunrise"]] = "sunrise"
            events[times["sunset"]] = "sunset"
        day += timedelta(days=1)
    return sorted((moment, kind) for moment, kind in events.items() if start - _MARGIN <= moment <= end + _MARGIN)
