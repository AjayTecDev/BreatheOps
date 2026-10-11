
"""EnvironmentalProvider abstraction: Replay | Live | Resilient."""
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Callable, Optional, Protocol

from .ingest import normalize_reading
from .models import Snapshot
from .trust import freshness
from . import seed


def parse_openaq_latest(raw: dict) -> dict:
    """Convert OpenAQ v3 latest readings into BreatheOps input."""

    if not isinstance(raw, dict) or not isinstance(raw.get("results"), list):
        raise ValueError("Invalid OpenAQ response")

    # PM2.5 sensor IDs listed for Naubad, Bidar - KSPCB.
    pm25_sensor_ids = {12362355, 245742}
    candidates = []

    for item in raw["results"]:
        if not isinstance(item, dict):
            continue

        try:
            sensor_id = int(item["sensorsId"])
            value = float(item["value"])
            timestamp = datetime.fromisoformat(
                str(item["datetime"]["utc"]).replace("Z", "+00:00")
            )
        except (TypeError, ValueError, KeyError):
            continue

        if sensor_id not in pm25_sensor_ids:
            continue

        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        else:
            timestamp = timestamp.astimezone(timezone.utc)

        # Conservative prototype data-quality limit.
        # This does not prove that the original sensor is faulty.
        if value < 0 or value > 500:
            continue

        candidates.append((timestamp, value))

    if not candidates:
        raise ValueError("No valid PM2.5 measurement found")

    timestamp, pm25 = max(candidates, key=lambda item: item[0])

    return {
        "pm25": pm25,
        "observed_at": timestamp.isoformat(),
        "source": "OpenAQ",
        "station": "Naubad, Bidar - KSPCB",
    }


@dataclass(frozen=True)
class ProviderResult:
    snapshot: Optional[Snapshot]
    issues: tuple = ()


class EnvironmentalProvider(Protocol):
    def get_snapshot(self, now: datetime) -> ProviderResult:
        ...


# Both names are used in project documentation.
EnvironmentProvider = EnvironmentalProvider


class ReplayProvider:
    """Controlled demo scenario. Labeled REPLAY downstream."""

    def __init__(self, aqi: float = 238.0, age_minutes: int = 8):
        self.aqi = aqi
        self.age = age_minutes

    def get_snapshot(self, now: datetime) -> ProviderResult:
        return ProviderResult(seed.demo_snapshot(now, self.aqi, self.age))


def _http_get_json(url: str, headers: dict, timeout: float) -> dict:
    """Fetch JSON from the configured data source."""
    req = urllib.request.Request(url, headers=headers)

    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


class LiveProvider:
    """Fetch and validate readings from a configured live data source."""

    def __init__(
        self,
        url: str = "",
        api_key: str = "",
        fetch: Callable = _http_get_json,
        parser: Callable[[dict], dict] = lambda raw: raw,
        auth_header: str = "X-API-Key",
        timeout: float = 5.0,
    ):
        self.url = url
        self.key = api_key
        self.fetch = fetch
        self.parser = parser
        self.auth_header = auth_header
        self.timeout = timeout

    def get_snapshot(self, now: datetime) -> ProviderResult:
        if not self.url or not self.key:
            return ProviderResult(
                None, ("live provider not configured",)
            )

        try:
            response = self.fetch(
                self.url,
                {self.auth_header: self.key},
                self.timeout,
            )
            raw = self.parser(response)
        except Exception as exc:
            # Do not expose URLs, credentials, or raw response data.
            return ProviderResult(
                None,
                (f"live fetch failed ({type(exc).__name__})",),
            )

        snap, issues = normalize_reading(raw, now, "LIVE")

        if snap is None:
            return ProviderResult(None, tuple(issues))

        age = freshness(snap.observed_at, now)["age_minutes"]

        # Reject future timestamps and observations older than 3 hours.
        if age is None or age < 0 or age > 180:
            return ProviderResult(
                None,
                tuple(issues)
                + ("OpenAQ reading is outside the accepted freshness window",),
            )

        return ProviderResult(
            replace(snap, retrieved_at=now),
            tuple(issues),
        )


class ResilientProvider:
    """Use primary data, then recent trusted LIVE data, otherwise unavailable."""

    def __init__(
        self,
        primary: EnvironmentalProvider,
        last_known: Callable[[], Optional[Snapshot]] = lambda: None,
        max_age_min: int = 180,
    ):
        self.primary = primary
        self.last_known = last_known
        self.max_age = max_age_min

    def get_snapshot(self, now: datetime) -> ProviderResult:
        result = self.primary.get_snapshot(now)

        if result.snapshot is not None:
            return result

        last = self.last_known()

        if last is not None:
            age = freshness(last.observed_at, now)["age_minutes"]

            if age is not None and 0 <= age <= self.max_age:
                return ProviderResult(
                    replace(last, quality="DEGRADED"),
                    result.issues
                    + (f"using last trusted reading ({age} min old)",),
                )

        return ProviderResult(
            None,
            result.issues + ("no acceptable environmental snapshot",),
        )
