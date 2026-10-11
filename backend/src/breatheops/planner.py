"""Deterministic planner + AI-output guardrails (locked AI response schema).

AI recommendation schema (one object per activity, exactly once each):
  {"activity_id": str, "action": <feasible action>, "reason": str(<=400),
   "evidence": [str(<=120)] (1-4 items), "confidence": High|Medium|Low,
   "modeled_impact": {"before": number, "after": number}}   # must equal the engine's numbers
Rejected -> deterministic plan. Anything the AI says is checked against the engine's data.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from .models import Action
from .candidates import Candidate

PREFERENCE = {Action.MOVE_INDOORS: 0, Action.RESCHEDULE: 1, Action.SHORTEN: 2}
CONFIDENCE = {"High", "Medium", "Low"}
NUM = re.compile(r"\d+(?:\.\d+)?")
MEDICAL = re.compile(r"diagnos|asthma|disease|illness|cancer|mortality|lung|respirator|medical|symptom", re.I)
TOL = 0.011


@dataclass(frozen=True)
class Recommendation:
    activity_id: str
    action: Action
    candidate: Candidate
    reason: str
    confidence: str
    evidence: tuple = ()


def deterministic_pick(cands: list[Candidate], band: str) -> Candidate:
    keep = next(c for c in cands if c.action == Action.KEEP)
    if band == "LOW":
        return keep  # good air / indoor: never recommend unnecessary changes
    movers = [c for c in cands if c.action in PREFERENCE and c.delta > 0]
    if movers:
        return max(movers, key=lambda c: (round(c.delta, 6), -PREFERENCE[c.action]))
    mon = [c for c in cands if c.action == Action.MONITOR]
    return mon[0] if mon else keep


def numbers_in(obj) -> list[float]:
    import json
    return [float(x) for x in NUM.findall(json.dumps(obj))]


def _grounded(tok: str, allowed: list[float]) -> bool:
    d = len(tok.split(".")[1]) if "." in tok else 0
    x = float(tok)
    return any(round(n, d) == x for n in allowed)


def validate_ai_output(raw, candidates: dict[str, list[Candidate]], context: dict | None = None) -> tuple[bool, list[str]]:
    errs: list[str] = []
    recs = raw.get("recommendations") if isinstance(raw, dict) else None
    if not isinstance(recs, list):
        return False, ["missing 'recommendations' list"]
    allowed = numbers_in(context) if context is not None else None
    seen = set()
    for r in recs:
        if not isinstance(r, dict):
            errs.append("recommendation is not an object"); continue
        aid = r.get("activity_id")
        if aid not in candidates:
            errs.append(f"unknown activity_id: {aid!r}"); continue
        if aid in seen:
            errs.append(f"duplicate recommendation for {aid}"); continue
        seen.add(aid)
        chosen = next((c for c in candidates[aid] if c.action.value == r.get("action")), None)
        if chosen is None:
            allowed_actions = sorted(c.action.value for c in candidates[aid])
            errs.append(f"{aid}: action {r.get('action')!r} not feasible (allowed: {allowed_actions})")
        if r.get("confidence") not in CONFIDENCE:
            errs.append(f"{aid}: invalid confidence")
        reason, ev = r.get("reason"), r.get("evidence")
        if not (isinstance(reason, str) and reason.strip()):
            errs.append(f"{aid}: empty reason"); reason = ""
        elif len(reason) > 400:
            errs.append(f"{aid}: reason too long")
        if not (isinstance(ev, list) and 1 <= len(ev) <= 4 and all(isinstance(e, str) and 0 < len(e) <= 120 for e in ev)):
            errs.append(f"{aid}: evidence must be 1-4 short strings"); ev = []
        text = reason + " " + " ".join(ev)
        if MEDICAL.search(text):
            errs.append(f"{aid}: medical claim not allowed")
        if allowed is not None:
            for tok in NUM.findall(text):
                if not _grounded(tok, allowed):
                    errs.append(f"{aid}: number {tok} not found in provided data")
        mi = r.get("modeled_impact")
        num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)
        if not (isinstance(mi, dict) and num(mi.get("before")) and num(mi.get("after"))):
            errs.append(f"{aid}: modeled_impact needs numeric before/after")
        elif chosen is not None and (abs(mi["before"] - (chosen.dose + chosen.delta)) > TOL
                                     or abs(mi["after"] - chosen.dose) > TOL):
            errs.append(f"{aid}: modeled_impact does not match the engine")
    missing = set(candidates) - seen
    if missing:
        errs.append(f"missing activities: {sorted(missing)}")
    return (not errs), errs
