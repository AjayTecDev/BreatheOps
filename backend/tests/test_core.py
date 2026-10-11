import sys, dataclasses
from datetime import datetime, timedelta
import os; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import pytest
from breatheops import seed
from breatheops.analyze import analyze
from breatheops.exposure import severity, dose, index_vs_baseline
from breatheops.candidates import generate
from breatheops.models import Action, hm
from breatheops.trust import freshness
from breatheops.planner import validate_ai_output

NOW = datetime(2026, 10, 10, 8, 40)


def run(aqi=238, age=8, acts=None, zones=None, **kw):
    return analyze(acts or seed.ACTIVITIES, zones or seed.ZONES, seed.demo_snapshot(NOW, aqi, age), NOW, *seed.DAY, **kw)


def test_severity_anchors_and_interpolation():
    assert severity(0) == 0 and severity(500) == 1.0 and severity(900) == 1.0
    assert severity(200) == pytest.approx(0.35)
    assert severity(250) == pytest.approx(0.50)

def test_deterministic_and_indoor_lower():
    assert dose(238, False, "vigorous", 60) == dose(238, False, "vigorous", 60)
    assert dose(238, True, "sedentary", 30) < dose(238, False, "sedentary", 30)

def test_duration_matters():
    assert dose(238, False, "light", 20) < dose(238, False, "light", 60)

def test_demo_scenario_actions():
    r = run()
    acts = {p["activity_id"]: p["action"] for p in r["plan"]}
    assert acts == {"a1": "MOVE_INDOORS", "a2": "KEEP", "a3": "SHORTEN", "a4": "KEEP", "a5": "MONITOR"}
    bands = {b["name"]: b["risk"] for b in r["risk_board"]}
    assert bands["Sports"] == "HIGH" and bands["Mathematics"] == "LOW"
    assert r["impact"]["proposed_index"] < 100

def test_good_air_no_unnecessary_changes():
    r = run(aqi=40)
    assert all(p["action"] == "KEEP" for p in r["plan"])
    assert r["impact"]["pct_lower"] == 0

def test_no_indoor_zone_for_sports():
    sports = seed.ACTIVITIES[2]
    c = generate(sports, seed.ACTIVITIES, seed.ZONES, lambda m: 238, *seed.DAY)
    assert Action.MOVE_INDOORS not in {x.action for x in c}

def test_capacity_blocks_move_indoors():
    big = dataclasses.replace(seed.ACTIVITIES[0], occupancy=1600)
    c = generate(big, [big] + seed.ACTIVITIES[1:], seed.ZONES, lambda m: 238, *seed.DAY)
    assert Action.MOVE_INDOORS not in {x.action for x in c}

def test_reschedule_only_with_forecast():
    bus = seed.ACTIVITIES[4]
    none = generate(bus, seed.ACTIVITIES, seed.ZONES, lambda m: 238, *seed.DAY)
    assert Action.RESCHEDULE not in {x.action for x in none}
    better = generate(bus, seed.ACTIVITIES, seed.ZONES, lambda m: 238 if m < hm("15:30") else 120, *seed.DAY)
    assert Action.RESCHEDULE in {x.action for x in better}

def test_trust_freshness():
    assert freshness(NOW - timedelta(minutes=8), NOW)["status"] == "FRESH"
    assert freshness(NOW - timedelta(minutes=120), NOW)["confidence"] == "Medium"
    assert freshness(NOW - timedelta(minutes=300), NOW)["status"] == "STALE"
    assert freshness(None, NOW)["status"] == "UNAVAILABLE"

def test_stale_data_lowers_confidence():
    assert {p["confidence"] for p in run(age=300)["plan"]} == {"Low"}

def _ai(action_overrides=None, drop=None):
    recs = [{"activity_id": p["activity_id"], "action": p["action"], "reason": "ok", "evidence": ["AQI 238 (Poor)"],
             "confidence": "High", "modeled_impact": p["modeled_impact"]} for p in run()["plan"]]
    for r in recs:
        if action_overrides and r["activity_id"] in action_overrides:
            r["action"] = action_overrides[r["activity_id"]]
    return {"recommendations": [r for r in recs if r["activity_id"] != drop]}

def test_valid_ai_output_accepted():
    r = run(ai_output=_ai())
    assert r["ai"]["used_fallback"] is False

def test_infeasible_ai_action_rejected_and_falls_back():
    r = run(ai_output=_ai({"a3": "MOVE_INDOORS"}))   # sports cannot go indoors
    assert r["ai"]["used_fallback"] is True and r["ai"]["validation_errors"]
    assert {p["activity_id"]: p["action"] for p in r["plan"]}["a3"] == "SHORTEN"

def test_hallucinated_activity_and_missing_rejected():
    cands = {"a1": generate(seed.ACTIVITIES[0], seed.ACTIVITIES, seed.ZONES, lambda m: 238, *seed.DAY)}
    ok, errs = validate_ai_output({"recommendations": [{"activity_id": "zzz", "action": "KEEP",
                                   "reason": "x", "evidence": ["e"], "confidence": "High", "modeled_impact": {"before": 0, "after": 0}}]}, cands)
    assert not ok and any("unknown" in e for e in errs)
    assert not validate_ai_output("garbage", cands)[0]
    assert not run(ai_output=_ai(drop="a5"))["ai"]["used_fallback"] is False

def test_index_helper():
    assert index_vs_baseline(0, 0) == (100.0, 0.0)
    assert index_vs_baseline(200, 100) == (50.0, 50.0)
