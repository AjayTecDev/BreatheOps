"""Data Trust Layer, part 1: validate + normalize a raw reading into a Snapshot.
No network code yet: a LIVE adapter (CPCB/OpenAQ) will return the raw dict shape below.
Never fabricate: anything invalid -> (None, issues)."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from .models import Snapshot

# CPCB National AQI PM2.5 breakpoints (ug/m3 -> sub-index). Verify against current CPCB docs.
_PM25 = [(0, 30, 0, 50), (31, 60, 51, 100), (61, 90, 101, 200),
         (91, 120, 201, 300), (121, 250, 301, 400), (251, 500, 401, 500)]


def pm25_to_aqi(pm25) -> float | None:
    if not isinstance(pm25, (int, float)) or isinstance(pm25, bool) or pm25 < 0:
        return None
    c = min(float(pm25), 500.0)
    for blo, bhi, ilo, ihi in _PM25:
        if c <= bhi:
            return max(float(ilo), (ihi - ilo) / (bhi - blo) * (c - blo) + ilo)
    return 500.0


def _naive_utc(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


def normalize_reading(raw: dict, now: datetime, mode: str = "LIVE") -> tuple[Snapshot | None, list[str]]:
    issues: list[str] = []
    try:
        ts = _naive_utc(datetime.fromisoformat(str(raw.get("observed_at")).replace("Z", "+00:00")))
    except ValueError:
        return None, ["observed_at missing or unparsable"]
    if ts > now + timedelta(minutes=5):
        return None, ["observed_at is in the future"]
    pm25 = raw.get("pm25")
    pm25 = pm25 if isinstance(pm25, (int, float)) and not isinstance(pm25, bool) and 0 <= pm25 <= 1000 else None
    aqi = raw.get("aqi")
    if not isinstance(aqi, (int, float)) or isinstance(aqi, bool) or not 0 <= aqi <= 500:
        aqi = None
    derived = False
    if aqi is None:
        aqi = pm25_to_aqi(pm25)
        if aqi is not None:
            derived = True
            issues.append("AQI derived from PM2.5 (instantaneous, not 24h average)")
    if aqi is None:
        return None, issues + ["no valid AQI or PM2.5"]
    return Snapshot(float(aqi), pm25, raw.get("source", "unknown"), raw.get("station", "unknown"),
                    ts, mode, None, "DERIVED" if derived else "OK"), issues
