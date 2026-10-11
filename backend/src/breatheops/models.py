from __future__ import annotations
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

_ID = re.compile(r"^[A-Za-z0-9_.-]{1,40}$")
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
INTENSITIES = ("sedentary", "light", "vigorous")


class Action(str, Enum):
    KEEP = "KEEP"
    MOVE_INDOORS = "MOVE_INDOORS"
    RESCHEDULE = "RESCHEDULE"
    SHORTEN = "SHORTEN"
    MONITOR = "MONITOR"


def hm(s: str) -> int:
    """'09:30' -> minutes since midnight. Strict: raises ValueError on anything else."""
    if not isinstance(s, str) or not _HHMM.match(s):
        raise ValueError(f"invalid time {s!r}, expected HH:MM")
    return int(s[:2]) * 60 + int(s[3:])


def fmt(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


@dataclass(frozen=True)
class Zone:
    zone_id: str
    name: str
    indoor: bool
    capacity: int
    supports: frozenset  # activity kinds this zone can physically host

    def __post_init__(self):
        if not _ID.match(str(self.zone_id)): raise ValueError("invalid zone_id")
        if not str(self.name).strip(): raise ValueError("zone name required")
        if not _int(self.capacity) or self.capacity <= 0: raise ValueError("zone capacity must be a positive integer")


@dataclass(frozen=True)
class Activity:
    activity_id: str
    name: str
    kind: str          # assembly | class | sports | lunch | transit
    start: int         # minutes since midnight
    duration: int      # minutes
    zone_id: str
    occupancy: int
    intensity: str     # sedentary | light | vigorous

    def __post_init__(self):
        if not _ID.match(str(self.activity_id)): raise ValueError("invalid activity_id")
        if not _ID.match(str(self.zone_id)): raise ValueError("invalid zone_id")
        if not str(self.name).strip() or not str(self.kind).strip(): raise ValueError("name and kind required")
        if not _int(self.start) or not 0 <= self.start <= 1439: raise ValueError("start must be 00:00-23:59")
        if not _int(self.duration) or not 1 <= self.duration <= 480: raise ValueError("duration must be 1-480 minutes")
        if not _int(self.occupancy) or self.occupancy < 0: raise ValueError("occupancy cannot be negative")
        if self.intensity not in INTENSITIES: raise ValueError(f"intensity must be one of {INTENSITIES}")

    @property
    def end(self) -> int:
        return self.start + self.duration


@dataclass(frozen=True)
class Snapshot:
    aqi: float
    pm25: float | None
    source: str
    station: str
    observed_at: datetime
    mode: str = "REPLAY"          # LIVE | REPLAY
    retrieved_at: datetime | None = None
    quality: str = "OK"           # OK | DERIVED (AQI from PM2.5) | DEGRADED (last-known reading)
    snapshot_id: str | None = None
