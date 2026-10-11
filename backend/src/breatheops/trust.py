"""Data Trust Layer: freshness + confidence. Never fabricate missing values."""
from __future__ import annotations
from datetime import datetime


def freshness(observed_at: datetime | None, now: datetime) -> dict:
    if observed_at is None:
        return {"status": "UNAVAILABLE", "age_minutes": None, "confidence": "Low"}
    age = max(0, int((now - observed_at).total_seconds() // 60))
    if age <= 60:
        status, conf = "FRESH", "High"
    elif age <= 180:
        status, conf = "AGING", "Medium"
    else:
        status, conf = "STALE", "Low"
    return {"status": status, "age_minutes": age, "confidence": conf}
