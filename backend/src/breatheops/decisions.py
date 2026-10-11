"""Human-in-the-loop decisions + audit trail. AI recommends; the admin decides."""
from __future__ import annotations
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Sequence
from .candidates import evaluate_custom
from .exposure import index_vs_baseline
from .models import Activity, Zone, fmt

DECISIONS = {"APPROVE", "MODIFY", "REJECT"}


@dataclass(frozen=True)
class Ctx:  # needed only to validate MODIFY
    activities: Sequence[Activity]
    zones: Sequence[Zone]
    aqi_at: Callable[[int], float]
    day_start: int
    day_end: int


def _shape(action, detail, start, duration, zone, dose_after) -> dict:
    return {"action": action, "detail": detail, "new_start": start,
            "new_duration": duration, "new_zone": zone, "modeled_dose_after": dose_after}


def record_decision(analysis: dict, activity_id: str, decision: str, admin: str, now: datetime,
                    modification: dict | None = None, note: str | None = None,
                    ctx: Ctx | None = None) -> dict:
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {sorted(DECISIONS)}")
    rec = next((p for p in analysis["plan"] if p["activity_id"] == activity_id), None)
    row = next((b for b in analysis["risk_board"] if b["activity_id"] == activity_id), None)
    if rec is None or row is None:
        raise ValueError(f"unknown activity {activity_id!r}")
    original = _shape(rec["action"], rec["detail"], rec["new_start"], rec["new_duration"],
                      rec["new_zone"], rec["modeled_impact"]["after"])
    if decision == "APPROVE":
        final = dict(original)
    elif decision == "REJECT":
        final = _shape("KEEP", "Rejected: schedule unchanged", row["time"], row["duration"],
                       row["zone"], row["dose"])
    else:
        if not modification or ctx is None:
            raise ValueError("MODIFY needs a modification and a validation context")
        a = next(x for x in ctx.activities if x.activity_id == activity_id)
        c = evaluate_custom(a, ctx.activities, ctx.zones, ctx.aqi_at, ctx.day_start, ctx.day_end,
                            **modification)
        zname = next(z.name for z in ctx.zones if z.zone_id == c.zone_id)
        final = _shape(c.action.value, c.note, fmt(c.start), c.duration, zname, round(c.dose, 2))
    return {"decision_id": uuid.uuid4().hex, "analysis_id": analysis.get("analysis_id"), "activity_id": activity_id, "decision": decision,
            "decided_by": admin, "decided_at": now.isoformat(), "note": note,
            "original_recommendation": original, "final": final}


def impact_after_decisions(analysis: dict, decisions: Sequence[dict]) -> dict:
    """Index of the schedule the admin actually chose; undecided activities stay unchanged."""
    if analysis.get("impact") is None:
        return None
    latest = {d["activity_id"]: d for d in decisions}
    before = sum(b["dose"] for b in analysis["risk_board"])
    after = sum(latest[b["activity_id"]]["final"]["modeled_dose_after"] if b["activity_id"] in latest
                else b["dose"] for b in analysis["risk_board"])
    idx, pct = index_vs_baseline(before, after)
    return {"baseline_index": 100.0, "final_index": idx, "pct_lower": pct,
            "decided": len(latest), "total": len(analysis["risk_board"])}


STATUS = {"APPROVE": "APPROVED", "MODIFY": "MODIFIED", "REJECT": "REJECTED"}


def history_item(analysis: dict, decisions: Sequence[dict]) -> dict:
    latest = {d["activity_id"]: d["decision"] for d in decisions}
    env, imp = analysis["environment"], impact_after_decisions(analysis, decisions)
    pending = [p for p in analysis["plan"] if p["action"] != "KEEP" and p["activity_id"] not in latest]
    return {"analysis_id": analysis.get("analysis_id"), "created_at": analysis.get("created_at"),
            "aqi": env["aqi"], "category": env["category"], "mode": env["mode"], "label": env["label"],
            "high_risk": sum(1 for b in analysis["risk_board"] if b["risk"] == "HIGH"),
            "recommendations": sum(1 for p in analysis["plan"] if p["action"] != "KEEP"),
            "approved": sum(v == "APPROVE" for v in latest.values()),
            "modified": sum(v == "MODIFY" for v in latest.values()),
            "rejected": sum(v == "REJECT" for v in latest.values()),
            "pending": len(pending), "final_index": imp["final_index"] if imp else None,
            "ai_fallback": bool(analysis["ai"]["used_fallback"] and analysis["ai"].get("attempted"))}


def daily_plan(school: dict, analysis: dict, decisions: Sequence[dict]) -> dict:
    latest = {d["activity_id"]: d for d in decisions}
    rows = {b["activity_id"]: b for b in analysis["risk_board"]}
    items = []
    for p in analysis["plan"]:
        d, b = latest.get(p["activity_id"]), rows[p["activity_id"]]
        if d:
            status, f = STATUS[d["decision"]], d["final"]
        else:
            status = "NO_CHANGE" if p["action"] == "KEEP" else "PENDING"
            f = {"action": p["action"], "detail": p["detail"], "new_start": p["new_start"],
                 "new_duration": p["new_duration"], "new_zone": p["new_zone"]}
        items.append({"activity_id": p["activity_id"], "time": b["time"], "activity": b["name"], "risk": b["risk"],
                      "status": status, "action": f["action"], "detail": f["detail"],
                      "new_start": f["new_start"], "new_duration": f["new_duration"], "new_zone": f["new_zone"],
                      "decided_by": d["decided_by"] if d else None, "decided_at": d["decided_at"] if d else None,
                      "note": d["note"] if d else None})
    env = analysis["environment"]
    return {"date": (analysis.get("created_at") or "")[:10], "school": school.get("name"),
            "analysis_id": analysis.get("analysis_id"),
            "environment": {k: env[k] for k in ("aqi", "category", "label", "status", "confidence")},
            "items": items, "prepared_by": sorted({d["decided_by"] for d in latest.values()}),
            "impact": impact_after_decisions(analysis, decisions), "disclaimer": analysis["disclaimer"]}
