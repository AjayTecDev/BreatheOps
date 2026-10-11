import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from datetime import datetime, timedelta
import pytest
from breatheops import seed
from breatheops.analyze import analyze
from breatheops.ai import make_ranker
from breatheops.decisions import record_decision, impact_after_decisions, Ctx
from breatheops.ingest import pm25_to_aqi, normalize_reading
from breatheops.models import hm

NOW = datetime(2026, 10, 10, 8, 40)
DOCS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "docs")


def run(**kw):
    age = kw.pop("age", 8)
    return analyze(seed.ACTIVITIES, seed.ZONES, seed.demo_snapshot(NOW, 238, age), NOW, *seed.DAY, **kw)

def ai_json(overrides=None, conf="High"):
    recs = [{"activity_id": p["activity_id"], "action": p["action"], "reason": "ok", "evidence": ["AQI 238 (Poor)"],
             "confidence": conf, "modeled_impact": p["modeled_impact"]} for p in run()["plan"]]
    for r in recs:
        r["action"] = (overrides or {}).get(r["activity_id"], r["action"])
    return json.dumps({"recommendations": recs})

class Fake:
    def __init__(self, text=None, exc=None): self.text, self.exc, self.calls = text, exc, []
    def converse(self, **kw):
        self.calls.append(kw)
        if self.exc: raise self.exc
        return {"output": {"message": {"content": [{"text": self.text}]}}}

# ---- Bedrock path ----
def test_bedrock_valid_response_used_even_with_markdown_fences():
    f = Fake("```json\n" + ai_json() + "\n```")
    r = run(ai_ranker=make_ranker(f, "model-x"))
    assert r["ai"]["used_fallback"] is False and f.calls[0]["modelId"] == "model-x"
    assert f.calls[0]["inferenceConfig"]["temperature"] == 0

def test_model_never_sees_infeasible_actions():
    sent = {}
    def spy(ctx): sent.update(ctx); return None
    run(ai_ranker=spy)
    sports = next(a for a in sent["activities"] if a["name"] == "Sports")
    assert "MOVE_INDOORS" not in {x["action"] for x in sports["feasible_actions"]}

@pytest.mark.parametrize("fake", [Fake("not json at all"), Fake(exc=TimeoutError("boom")),
                                  Fake(ai_json({"a3": "MOVE_INDOORS"}))])
def test_any_ai_failure_falls_back_and_workflow_continues(fake):
    r = run(ai_ranker=make_ranker(fake, "m"))
    assert r["ai"]["used_fallback"] is True
    assert {p["activity_id"]: p["action"] for p in r["plan"]}["a3"] == "SHORTEN"

def test_unconfigured_bedrock_falls_back(monkeypatch):
    monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)
    r = run(ai_ranker=make_ranker())
    assert r["ai"]["used_fallback"] and "BEDROCK_MODEL_ID" in r["ai"]["error"]

def test_ai_confidence_cannot_exceed_data_confidence():
    r = run(age=300, ai_ranker=make_ranker(Fake(ai_json(conf="High")), "m"))
    assert not r["ai"]["used_fallback"] and {p["confidence"] for p in r["plan"]} == {"Low"}

# ---- decisions / audit trail ----
def ctx(): return Ctx(seed.ACTIVITIES, seed.ZONES, lambda m: 238.0, *seed.DAY)

def test_approve_all_matches_proposed_index():
    a = run(); ds = [record_decision(a, p["activity_id"], "APPROVE", "admin", NOW) for p in a["plan"]]
    assert impact_after_decisions(a, ds)["final_index"] == a["impact"]["proposed_index"]
    assert ds[0]["decided_by"] == "admin" and ds[0]["original_recommendation"] == ds[0]["final"]

def test_reject_keeps_original_and_raises_index():
    a = run(); d = record_decision(a, "a3", "REJECT", "admin", NOW, note="exam day")
    assert d["final"]["action"] == "KEEP" and d["note"] == "exam day"
    assert impact_after_decisions(a, [d])["final_index"] == 100.0

def test_modify_is_validated_and_recorded():
    a = run()
    d = record_decision(a, "a3", "MODIFY", "admin", NOW, modification={"duration": 45}, ctx=ctx())
    assert d["final"]["action"] == "SHORTEN" and d["final"]["new_duration"] == 45
    assert d["original_recommendation"]["new_duration"] == 30
    for bad in ({"duration": 90}, {"zone_id": "main"}, {"start": hm("15:30")}):
        with pytest.raises(ValueError): record_decision(a, "a3", "MODIFY", "admin", NOW, modification=bad, ctx=ctx())

def test_bad_decision_inputs():
    a = run()
    with pytest.raises(ValueError): record_decision(a, "a3", "MAYBE", "admin", NOW)
    with pytest.raises(ValueError): record_decision(a, "nope", "APPROVE", "admin", NOW)

# ---- ingestion / trust ----
def test_pm25_conversion_and_seed_consistency():
    assert pm25_to_aqi(0) == 0 and pm25_to_aqi(30) == 50 and pm25_to_aqi(120) == 300
    assert pm25_to_aqi(-1) is None and pm25_to_aqi("x") is None
    assert abs(pm25_to_aqi(seed.demo_snapshot(NOW).pm25) - 238) < 1.0   # replay data is self-consistent

def test_normalize_rejects_bad_data_and_never_fabricates():
    ok = {"pm25": 100, "observed_at": (NOW - timedelta(minutes=5)).isoformat(), "source": "S", "station": "X"}
    s, issues = normalize_reading(ok, NOW)
    assert s.mode == "LIVE" and 200 < s.aqi < 300 and issues
    assert normalize_reading({**ok, "observed_at": (NOW + timedelta(hours=2)).isoformat()}, NOW)[0] is None
    assert normalize_reading({**ok, "observed_at": "garbage"}, NOW)[0] is None
    assert normalize_reading({"observed_at": ok["observed_at"], "pm25": None, "aqi": 9999}, NOW)[0] is None
    s2, _ = normalize_reading({**ok, "observed_at": "2026-10-10T08:35:00Z"}, NOW)   # tz-aware -> naive UTC
    assert s2.observed_at == datetime(2026, 10, 10, 8, 35)

def test_live_vs_replay_labels():
    assert run()["environment"]["label"].startswith("REPLAY")
    live, _ = normalize_reading({"pm25": 100, "observed_at": (NOW - timedelta(minutes=12)).isoformat(), "source": "CPCB"}, NOW)
    r = analyze(seed.ACTIVITIES, seed.ZONES, live, NOW, *seed.DAY)
    assert r["environment"]["label"] == "LIVE \u2014 CPCB \u2014 updated 12 min ago"

# ---- canonical demo: one source of truth ----
def test_canonical_demo_is_frozen():
    frozen = json.load(open(os.path.join(DOCS, "canonical_demo.json"), encoding="utf-8"))
    assert json.loads(json.dumps(run())) == frozen, "model drifted: run backend/freeze_demo.py AND update docs deliberately"

def test_docs_quote_canonical_numbers():
    c = json.load(open(os.path.join(DOCS, "canonical_demo.json"), encoding="utf-8"))
    pitch = open(os.path.join(DOCS, "PITCH.md"), encoding="utf-8").read()
    model = open(os.path.join(DOCS, "EXPOSURE_MODEL.md"), encoding="utf-8").read()
    assert str(c["impact"]["proposed_index"]) in pitch and str(c["impact"]["pct_lower"]) in pitch
    sports = next(b for b in c["risk_board"] if b["name"] == "Sports")
    after = next(p for p in c["plan"] if p["activity_id"] == "a3")["modeled_impact"]["after"]
    assert f"{sports['dose']:.1f}" in model and f"{after:.1f}" in model
