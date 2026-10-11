"""Orchestrates one 'Analyze Today's Schedule' run. Pure function, JSON-friendly output."""
from __future__ import annotations
from datetime import datetime
from typing import Callable, Optional, Sequence
from .models import Action, Activity, Snapshot, Zone, fmt
from .exposure import (ModelParams, DEFAULT, cpcb_category, dose, risk_band, index_vs_baseline)
from .candidates import generate
from .planner import Recommendation, deterministic_pick, validate_ai_output
from .trust import freshness
from .ai import build_context

CONF = {"Low": 0, "Medium": 1, "High": 2}
DISCLAIMER = "Modeled decision-support index. Not a clinical or epidemiological measure."


def _label(snap: Snapshot, trust: dict) -> str:
    if snap.mode == "REPLAY":
        return "REPLAY \u2014 Demonstration scenario"
    age = trust["age_minutes"]
    return f"LIVE \u2014 {snap.source} \u2014 " + (f"updated {age} min ago" if age is not None else "update time unavailable")


def _warnings(trust, snap, ai_attempted, used_fallback) -> list[dict]:
    w = []
    if trust["status"] == "STALE":
        w.append(("STALE_DATA", f"Data is {trust['age_minutes']} min old. Confidence reduced; re-check before acting."))
    elif trust["status"] == "AGING":
        w.append(("AGING_DATA", f"Data is {trust['age_minutes']} min old."))
    if snap.quality == "DEGRADED":
        w.append(("DEGRADED_DATA", "Live source unavailable; using the last trusted reading."))
    if snap.quality == "DERIVED":
        w.append(("DERIVED_AQI", "AQI derived from PM2.5 (instantaneous reading, not a 24h average)."))
    if ai_attempted and used_fallback:
        w.append(("AI_FALLBACK", "AI planner unavailable or its output was rejected; deterministic plan used."))
    return [{"code": c, "message": m} for c, m in w]


def _options(cs, zm) -> list[dict]:
    """Every feasible alternative the admin may choose when modifying; `modification` is ready to POST."""
    return [{"action": c.action.value, "detail": c.note, "modeled_after": round(c.dose, 2),
             "new_start": fmt(c.start), "new_duration": c.duration, "new_zone": zm[c.zone_id].name,
             "modification": {"zone_id": c.zone_id, "start": fmt(c.start), "duration": c.duration}} for c in cs]


def _unavailable(activities, zm, trust) -> dict:
    """No trusted environmental data: never fabricate. Show the timetable, recommend nothing."""
    board = [{"activity_id": a.activity_id, "name": a.name, "time": fmt(a.start), "duration": a.duration,
              "zone": zm[a.zone_id].name, "setting": "Indoor" if zm[a.zone_id].indoor else "Outdoor",
              "dose": None, "risk": None} for a in activities]
    return {"environment": {"aqi": None, "category": None, "pm25": None, "source": None, "station": None,
                            "mode": None, "snapshot_id": None, "label": "Environmental data unavailable", "observed_at": None,
                            "retrieved_at": None, "quality": None, **trust},
            "risk_board": board, "plan": [], "impact": None,
            "ai": {"attempted": False, "used_fallback": False, "validation_errors": [], "error": None},
            "warnings": [{"code": "NO_ENV_DATA",
                          "message": "No trusted environmental data. No recommendations were generated."}],
            "disclaimer": DISCLAIMER}


def analyze(activities: Sequence[Activity], zones: Sequence[Zone], snapshot: Optional[Snapshot],
            now: datetime, day_start: int, day_end: int,
            hourly_aqi: Optional[dict] = None, ai_output: Optional[dict] = None,
            ai_ranker: Optional[Callable] = None, p: ModelParams = DEFAULT) -> dict:
    zm = {z.zone_id: z for z in zones}
    if snapshot is None:
        return _unavailable(activities, zm, freshness(None, now))
    trust = freshness(snapshot.observed_at, now)

    def aqi_at(minute: int) -> float:  # forecast only if provided; otherwise current snapshot
        return float(hourly_aqi.get(minute // 60, snapshot.aqi)) if hourly_aqi else snapshot.aqi

    cands = {a.activity_id: generate(a, activities, zones, aqi_at, day_start, day_end, p) for a in activities}
    risk = {}
    for a in activities:
        d = dose(aqi_at(a.start), zm[a.zone_id].indoor, a.intensity, a.duration, p)
        risk[a.activity_id] = (d, risk_band(d, p))
    context = build_context(snapshot, trust, activities, zm, risk, cands)

    ai_attempted = ai_output is not None or ai_ranker is not None
    ai_error = None
    if ai_output is None and ai_ranker is not None:
        try:  # AI failure must never break the safety workflow
            ai_output = ai_ranker(context)
        except Exception as e:
            ai_error = f"{type(e).__name__}: {e}"
        if ai_output is None and ai_error is None:
            ai_error = "AI returned no parsable output"

    used_fallback, ai_errors, ai_by_id = True, [], {}
    if ai_output is not None:
        ok, ai_errors = validate_ai_output(ai_output, cands, context)
        if ok:
            used_fallback = False
            ai_by_id = {r["activity_id"]: r for r in ai_output["recommendations"]}

    age_txt = "age unknown" if trust["age_minutes"] is None else f"{trust['age_minutes']} min old"
    recs: list[Recommendation] = []
    for a in activities:
        d, band = risk[a.activity_id]
        setting = "indoor" if zm[a.zone_id].indoor else "outdoor"
        if a.activity_id in ai_by_id:
            r = ai_by_id[a.activity_id]
            cand = next(c for c in cands[a.activity_id] if c.action.value == r["action"])
            conf = r["confidence"] if CONF[r["confidence"]] <= CONF[trust["confidence"]] else trust["confidence"]
            recs.append(Recommendation(a.activity_id, cand.action, cand, r["reason"], conf, tuple(r["evidence"])))
        else:
            cand = deterministic_pick(cands[a.activity_id], band)
            reason = (f"{band} modeled exposure ({d:.1f} weighted-min): {setting} {a.name.lower()}, "
                      f"{a.duration} min at AQI {snapshot.aqi:.0f} ({cpcb_category(snapshot.aqi)}). {cand.note}.")
            ev = (f"AQI {snapshot.aqi:.0f} ({cpcb_category(snapshot.aqi)})", f"{setting.capitalize()}, {a.duration} min",
                  f"Data {trust['status'].lower()}, {age_txt}")
            recs.append(Recommendation(a.activity_id, cand.action, cand, reason, trust["confidence"], ev))

    before = sum(d for d, _ in risk.values())
    after = sum(r.candidate.dose for r in recs)
    idx, pct = index_vs_baseline(before, after)
    order = {"HIGH": 1, "MEDIUM": 2, "LOW": 3}
    board = [{"activity_id": a.activity_id, "name": a.name, "time": fmt(a.start),
              "duration": a.duration, "zone": zm[a.zone_id].name,
              "setting": "Indoor" if zm[a.zone_id].indoor else "Outdoor",
              "dose": round(risk[a.activity_id][0], 2), "risk": risk[a.activity_id][1]} for a in activities]
    plan = [{"activity_id": r.activity_id, "action": r.action.value,
             "priority": order[risk[r.activity_id][1]] if r.action != Action.KEEP else None,
             "detail": r.candidate.note, "reason": r.reason, "evidence": list(r.evidence),
             "confidence": r.confidence,
             "modeled_impact": {"before": round(risk[r.activity_id][0], 2), "after": round(r.candidate.dose, 2)},
             "new_start": fmt(r.candidate.start), "new_duration": r.candidate.duration,
             "new_zone": zm[r.candidate.zone_id].name,
             "options": _options(cands[r.activity_id], zm)} for r in recs]
    return {
        "environment": {"aqi": snapshot.aqi, "category": cpcb_category(snapshot.aqi),
                        "pm25": snapshot.pm25, "source": snapshot.source, "station": snapshot.station,
                        "mode": snapshot.mode, "snapshot_id": snapshot.snapshot_id, "label": _label(snapshot, trust),
                        "observed_at": snapshot.observed_at.isoformat(),
                        "retrieved_at": snapshot.retrieved_at.isoformat() if snapshot.retrieved_at else None,
                        "quality": snapshot.quality, **trust},
        "risk_board": board, "plan": plan,
        "impact": {"baseline_index": 100.0, "proposed_index": idx, "pct_lower": pct,
                   "label": f"{pct}% lower modeled exposure index under this scenario"},
        "ai": {"attempted": ai_attempted, "used_fallback": used_fallback,
               "validation_errors": ai_errors, "error": ai_error},
        "warnings": _warnings(trust, snapshot, ai_attempted, used_fallback),
        "disclaimer": DISCLAIMER,
    }
