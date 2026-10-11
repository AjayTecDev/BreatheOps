"""Transport layer: routing, request validation, auth, response envelope.

Success:
    {"success": true, "data": {...}, "request_id": "..."}

Error:
    {"success": false, "error": {"code": "...", "message": "..."}, ...}
"""

from __future__ import annotations

import re
import time
import uuid
from datetime import datetime, timezone
from typing import Callable, Mapping, Optional

from .ai import DeterministicPlanner
from .auth import AuthService, build_auth
from .config import Settings
from .errors import ServiceError, invalid
from .models import hm
from .observability import RequestLog
from .providers import (
    EnvironmentProvider,
    LiveProvider,
    parse_openaq_latest,
)
from .services import (
    AnalyzeService,
    CampusService,
    DailyPlanService,
    DecisionService,
    HistoryService,
)


SID = re.compile(r"^[a-z0-9][a-z0-9-]{1,39}$")
ID = re.compile(r"^[A-Za-z0-9_#:.-]{1,80}$")
HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
DECISIONS = ("APPROVE", "MODIFY", "REJECT")


def _num(v, lo, hi, name):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
        raise invalid(f"{name} must be a number between {lo} and {hi}")
    return float(v)


class App:
    def __init__(
        self,
        settings: Settings,
        repo,
        planner=None,
        live_provider: Optional[EnvironmentProvider] = None,
        clock: Optional[Callable[[], datetime]] = None,
        sink: Callable[[dict], None] = lambda e: None,
        auth: Optional[AuthService] = None,
    ):
        self.cfg, self.repo, self.sink = settings, repo, sink
        self.planner = planner or DeterministicPlanner()
        self.clock = clock or (
            lambda: datetime.now(timezone.utc).replace(tzinfo=None)
        )
        self.auth = auth or build_auth(settings)

        # OpenAQ integration: convert its API response into BreatheOps format.
        # A custom live_provider passed by tests or other callers still takes priority.
        live = live_provider or LiveProvider(
            settings.environment_api_url,
            settings.environment_api_key,
            parser=parse_openaq_latest,
        )

        self.campus = CampusService(repo)
        self.history = HistoryService(repo)
        self.daily = DailyPlanService(repo)
        self.decisions = DecisionService(repo, lambda: self.clock())

        self.analyzer = AnalyzeService(
            repo,
            settings,
            self.planner,
            live,
            lambda: self.clock(),
        )

        self.routes = {
            ("POST", "/analyze"): self._analyze,
            ("GET", "/school"): self._school,
            ("GET", "/zones"): self._zones,
            ("GET", "/activities"): self._activities,
            ("POST", "/decisions"): self._decisions,
            ("GET", "/history"): self._history,
            ("GET", "/daily-plan"): self._daily_plan,
        }

    # ---- Entry point ----

    def handle(
        self,
        method: str,
        path: str,
        query: Optional[dict] = None,
        body=None,
        headers: Optional[Mapping[str, str]] = None,
        request_id: Optional[str] = None,
    ):
        rid = request_id or uuid.uuid4().hex[:12]
        log = RequestLog(self.sink, rid)
        t0 = time.monotonic()
        path = path.rstrip("/") or "/"

        try:
            fn = self.routes.get((method.upper(), path))

            if fn is None:
                known = any(p == path for (_, p) in self.routes)
                raise ServiceError(
                    "METHOD_NOT_ALLOWED" if known else "NOT_FOUND",
                    "method not allowed" if known else "not found",
                    405 if known else 404,
                )

            principal = self.auth.authenticate(
                {k.lower(): v for k, v in (headers or {}).items()}
            )

            if body is not None and not isinstance(body, dict):
                raise invalid("request body must be a JSON object")

            status = 200
            env = {
                "success": True,
                "data": fn(query or {}, body or {}, principal, log),
            }

        except ServiceError as e:
            status = e.status
            env = {
                "success": False,
                "error": {"code": e.code, "message": e.message},
            }

        except Exception as e:
            # Do not expose internal details or secrets in API responses.
            log.event(
                "unhandled_error",
                level="ERROR",
                error_type=type(e).__name__,
                route=path,
            )
            status = 500
            env = {
                "success": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": (
                        "Something went wrong. "
                        "Quote the request id if you report it."
                    ),
                },
            }

        env["request_id"] = rid

        log.event(
            "request_completed",
            method=method.upper(),
            route=path,
            status=status,
            ms=int((time.monotonic() - t0) * 1000),
        )

        return status, env

    # ---- Validation helpers ----

    def _sid(self, q, b=None) -> str:
        sid = (
            (b or {}).get("school_id")
            or q.get("school_id")
            or self.cfg.default_school_id
        )

        if not isinstance(sid, str) or not SID.match(sid):
            raise invalid("invalid school_id")

        return sid

    # ---- Campus routes ----

    def _school(self, q, b, p, log):
        return self.campus.school(self._sid(q))

    def _zones(self, q, b, p, log):
        return self.campus.zones(self._sid(q))

    def _activities(self, q, b, p, log):
        return self.campus.activities(self._sid(q))

    # ---- Environmental analysis ----

    def _analyze(self, q, b, p, log):
        mode = str(
            b.get("mode") or self.cfg.environment_provider
        ).upper()

        if mode not in ("REPLAY", "LIVE"):
            raise invalid("mode must be REPLAY or LIVE")

        aqi = (
            _num(b["replay_aqi"], 0, 500, "replay_aqi")
            if "replay_aqi" in b
            else None
        )

        return self.analyzer.run(
            self._sid(q, b),
            mode,
            aqi,
            log,
        )

    # ---- Admin decisions ----

    def _decisions(self, q, b, p, log):
        sid = self._sid(q, b)
        aid = b.get("analysis_id")
        act = b.get("activity_id")

        if not (
            isinstance(aid, str)
            and ID.match(aid)
            and isinstance(act, str)
            and ID.match(act)
        ):
            raise invalid("analysis_id and activity_id are required")

        decision = str(b.get("decision", "")).upper()
        note = b.get("note")

        if decision not in DECISIONS:
            raise invalid(
                f"decision must be one of {list(DECISIONS)}"
            )

        if note is not None and not (
            isinstance(note, str) and len(note) <= 500
        ):
            raise invalid("note must be a string up to 500 characters")

        mod = b.get("modification")
        kwargs = None

        if mod is not None:
            if decision != "MODIFY":
                raise invalid(
                    "modification is only allowed with decision MODIFY"
                )

            if (
                not isinstance(mod, dict)
                or not mod
                or set(mod) - {"zone_id", "start", "duration"}
            ):
                raise invalid(
                    "modification may contain zone_id, start (HH:MM), duration"
                )

            kwargs = {}

            if "zone_id" in mod:
                if not (
                    isinstance(mod["zone_id"], str)
                    and ID.match(mod["zone_id"])
                ):
                    raise invalid("invalid zone_id")

                kwargs["zone_id"] = mod["zone_id"]

            if "start" in mod:
                if not (
                    isinstance(mod["start"], str)
                    and HHMM.match(mod["start"])
                ):
                    raise invalid("start must be HH:MM")

                kwargs["start"] = hm(mod["start"])

            if "duration" in mod:
                kwargs["duration"] = int(
                    _num(mod["duration"], 1, 480, "duration")
                )

        elif decision == "MODIFY":
            raise invalid("MODIFY requires a modification")

        return self.decisions.record(
            sid,
            aid,
            act,
            decision,
            p,
            note,
            kwargs,
            log,
        )

    # ---- History ----

    def _history(self, q, b, p, log):
        try:
            limit = max(1, min(30, int(q.get("limit", 10))))
        except (TypeError, ValueError):
            raise invalid("limit must be an integer")

        return self.history.list(self._sid(q), limit)

    # ---- Daily plan ----

    def _daily_plan(self, q, b, p, log):
        aid = q.get("analysis_id")

        if aid is not None and not (
            isinstance(aid, str) and ID.match(aid)
        ):
            raise invalid("invalid analysis_id")

        return self.daily.get(self._sid(q), aid)