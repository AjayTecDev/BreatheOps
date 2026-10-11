"""Application layer: orchestration + business rules. No HTTP, no AWS SDK. Talks to the repository contract."""
from __future__ import annotations
import time, uuid
from dataclasses import replace
from datetime import datetime
from typing import Callable, Optional
from .analyze import analyze
from .ai import DeterministicPlanner
from .decisions import Ctx, daily_plan, history_item, impact_after_decisions, record_decision
from .errors import ServiceError, conflict, not_found
from .models import fmt, hm
from .providers import ReplayProvider, ResilientProvider


def _school(repo, sid: str) -> dict:
    s = repo.get_school(sid)
    if s is None:
        raise not_found("unknown school")
    return s


def _new_id(now: datetime) -> str:
    return f"{now:%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"


class CampusService:
    def __init__(self, repo): self.repo = repo

    def school(self, sid):
        return {"school_id": sid, **_school(self.repo, sid)}

    def zones(self, sid):
        _school(self.repo, sid)
        return {"zones": [{"zone_id": z.zone_id, "name": z.name, "indoor": z.indoor, "capacity": z.capacity,
                           "supports": sorted(z.supports)} for z in self.repo.list_zones(sid)]}

    def activities(self, sid):
        _school(self.repo, sid)
        return {"activities": [{"activity_id": a.activity_id, "name": a.name, "kind": a.kind, "time": fmt(a.start),
                                "duration": a.duration, "zone_id": a.zone_id, "occupancy": a.occupancy,
                                "intensity": a.intensity} for a in self.repo.list_activities(sid)]}


class AnalyzeService:
    def __init__(self, repo, settings, planner, live_provider, clock: Callable[[], datetime]):
        self.repo, self.cfg, self.planner, self.live, self.clock = repo, settings, planner, live_provider, clock

    def run(self, sid: str, mode: str, replay_aqi: Optional[float], log) -> dict:
        t0 = time.monotonic()
        school = _school(self.repo, sid)
        acts, zones = self.repo.list_activities(sid), self.repo.list_zones(sid)
        if not acts or not zones:
            raise conflict("NO_TIMETABLE", "This school has no zones or timetable yet.")
        now = self.clock()
        use_ai = not isinstance(self.planner, DeterministicPlanner)
        log.event("analysis_started", school_id=sid, mode=mode, planner="bedrock" if use_ai else "deterministic")

        provider = (ReplayProvider(238.0 if replay_aqi is None else replay_aqi) if mode == "REPLAY"
                    else ResilientProvider(self.live, lambda: self.repo.latest_snapshot(sid, "LIVE")))
        t1 = time.monotonic()
        res = provider.get_snapshot(now)
        snap = res.snapshot
        log.event("environment_fetch", mode=mode, ok=snap is not None, quality=snap.quality if snap else None,
                  issues=len(res.issues), ms=int((time.monotonic() - t1) * 1000))
        if snap is None or snap.quality == "DEGRADED":
            log.event("provider_failure", level="WARN", mode=mode, issues=list(res.issues))
        if snap is not None and snap.snapshot_id is None:
            snap = replace(snap, snapshot_id=_new_id(now))
            self.repo.save_snapshot(sid, snap)

        def logged_rank(ctx):
            log.event("ai_requested", activities=len(ctx["activities"]))
            return self.planner.rank(ctx)
        ranker = logged_rank if use_ai else None
        out = analyze(acts, zones, snap, now, hm(school["day_start"]), hm(school["day_end"]), ai_ranker=ranker)
        out["warnings"] += [{"code": "PROVIDER", "message": m} for m in res.issues]
        aid = _new_id(now)
        out.update({"analysis_id": aid, "school_id": sid, "created_at": now.isoformat(), "plan_id": f"plan-{aid}"})
        out["ai"]["planner"] = "bedrock" if use_ai else "deterministic"
        for p in out["plan"]:
            p["recommendation_id"] = f"{aid}.{p['activity_id']}"
        if out["ai"]["attempted"] and out["ai"]["used_fallback"]:
            log.event("ai_fallback", level="WARN", error=out["ai"]["error"], rejected=len(out["ai"]["validation_errors"]))
        self.repo.save_analysis(sid, out)
        log.event("analysis_completed", analysis_id=aid, data_status=out["environment"]["status"],
                  ai_used=out["ai"]["attempted"] and not out["ai"]["used_fallback"], ms=int((time.monotonic() - t0) * 1000))
        return out


class DecisionService:
    def __init__(self, repo, clock): self.repo, self.clock = repo, clock

    def record(self, sid, analysis_id, activity_id, decision, principal, note, modification, log) -> dict:
        school = _school(self.repo, sid)
        analysis = self.repo.get_analysis(sid, analysis_id)
        if analysis is None:
            raise not_found("unknown analysis")
        if analysis["environment"]["aqi"] is None:
            raise conflict("ENVIRONMENT_UNAVAILABLE", "This analysis has no environmental data, so nothing can be decided.")
        rec = next((p for p in analysis["plan"] if p["activity_id"] == activity_id), None)
        if rec is None:
            raise not_found("unknown activity in this analysis")
        aqi = analysis["environment"]["aqi"]
        ctx = Ctx(self.repo.list_activities(sid), self.repo.list_zones(sid), lambda m: aqi,
                  hm(school["day_start"]), hm(school["day_end"]))
        try:
            d = record_decision(analysis, activity_id, decision, principal.name, self.clock(), modification, note, ctx)
        except ValueError as e:
            raise ServiceError("INFEASIBLE_MODIFICATION" if decision == "MODIFY" else "INVALID_REQUEST", str(e), 422)
        prior = [x for x in self.repo.list_decisions(sid, analysis_id)]
        previous = [x for x in prior if x["activity_id"] == activity_id]
        d.update({"recommendation_id": rec["recommendation_id"], "decided_by_id": principal.id,
                  "seq": len(prior) + 1, "supersedes": previous[-1]["decision_id"] if previous else None})
        self.repo.save_decision(sid, d)      # append-only: earlier decisions are never edited
        log.event("decision_created", analysis_id=analysis_id, activity_id=activity_id, decision=d["decision"],
                  decided_by_id=principal.id, supersedes=d["supersedes"])
        return {"decision": d, "impact": impact_after_decisions(analysis, prior + [d])}


class HistoryService:
    def __init__(self, repo): self.repo = repo

    def list(self, sid, limit: int) -> dict:
        _school(self.repo, sid)
        return {"history": [history_item(a, self.repo.list_decisions(sid, a["analysis_id"]))
                            for a in self.repo.list_analyses(sid, limit)]}


class DailyPlanService:
    def __init__(self, repo): self.repo = repo

    def get(self, sid, analysis_id: Optional[str]) -> dict:
        school = _school(self.repo, sid)
        if analysis_id:
            analysis = self.repo.get_analysis(sid, analysis_id)
        else:
            latest = self.repo.list_analyses(sid, 1)
            analysis = latest[0] if latest else None
        if analysis is None:
            raise not_found("no analysis found")
        plan = daily_plan(school, analysis, self.repo.list_decisions(sid, analysis["analysis_id"]))
        plan["plan_id"] = analysis.get("plan_id") or f"plan-{analysis['analysis_id']}"
        return plan
