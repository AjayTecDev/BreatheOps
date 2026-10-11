import sys, os, json, base64
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from datetime import datetime, timedelta
from decimal import Decimal
import pytest
from breatheops import seed
from breatheops.analyze import analyze
from breatheops.api import App
from breatheops.ai import BedrockPlanner
from breatheops.config import Settings
from breatheops.exposure import severity, index_vs_baseline
from breatheops.planner import validate_ai_output
from breatheops.candidates import generate
from breatheops.providers import LiveProvider
from breatheops.repository import DynamoStore, MemoryRepository, Repository, to_ddb, from_ddb

NOW = datetime(2026, 10, 10, 8, 40)


def call(app, method, path, query=None, body=None, headers=None):
    """Unwrap the {success, data} envelope; errors come back as the full envelope."""
    st, env = app.handle(method, path, query, body, {"x-admin-name": "Ms. Rao", **(headers or {})})
    return st, (env["data"] if env["success"] else env)


def make_app(planner=None, live=None, clock=NOW, settings=None):
    repo = MemoryRepository(); seed.seed_repository(repo)
    return App(settings or Settings(), repo, planner, live, lambda: clock), repo

def analyze_ok(app, **body):
    st, out = call(app, "POST", "/analyze", {}, body); assert st == 200, out; return out

# ---------- API ----------
def test_full_workflow_analyze_decide_plan_history():
    app, _ = make_app()
    a = analyze_ok(app)
    assert a["analysis_id"] and a["environment"]["label"].startswith("REPLAY") and a["impact"]["proposed_index"] == 60.1
    for act in ("a1", "a3"):
        assert call(app, "POST", "/decisions", {}, {"analysis_id": a["analysis_id"], "activity_id": act,
                          "decision": "approve", "admin": "Ms. Rao"})[0] == 200
    st, d = call(app, "POST", "/decisions", {}, {"analysis_id": a["analysis_id"], "activity_id": "a5",
                       "decision": "REJECT", "admin": "Ms. Rao", "note": "buses staggered"})
    assert st == 200 and d["impact"]["decided"] == 3
    st, plan = call(app, "GET", "/daily-plan", {"analysis_id": a["analysis_id"]})
    status = {i["activity"]: i["status"] for i in plan["items"]}
    assert status == {"Assembly": "APPROVED", "Mathematics": "NO_CHANGE", "Sports": "APPROVED", "Lunch": "NO_CHANGE", "Bus departure": "REJECTED"}
    assert plan["prepared_by"] == ["Ms. Rao"] and plan["school"] == "Green Valley Public School"
    st, h = call(app, "GET", "/history")
    row = h["history"][0]
    assert (row["approved"], row["rejected"], row["pending"], row["high_risk"]) == (2, 1, 0, 1)

def test_modify_via_api_and_validation_errors():
    app, _ = make_app(); a = analyze_ok(app)
    base = {"analysis_id": a["analysis_id"], "activity_id": "a3", "admin": "x"}
    st, d = call(app, "POST", "/decisions", {}, {**base, "decision": "MODIFY", "modification": {"duration": 45, "start": "12:00"}})
    assert st == 200 and d["decision"]["final"]["new_duration"] == 45
    for bad in ({"decision": "MODIFY", "modification": {"duration": 90}},        # infeasible -> 422
                {"decision": "MODIFY", "modification": {"zone_id": "main"}}):
        assert call(app, "POST", "/decisions", {}, {**base, **bad})[0] == 422
    for bad in ({"decision": "MODIFY", "modification": {"start": "25:00"}}, {"decision": "MODIFY", "modification": {"evil": 1}},
                {"decision": "APPROVE", "analysis_id": "../x"},
                {"decision": "APPROVE", "note": "n" * 501}, {"decision": "APPROVE", "school_id": "BAD ID"}):
        assert call(app, "POST", "/decisions", {}, {**base, **bad})[0] == 400, bad
    assert call(app, "POST", "/decisions", {}, {**base, "decision": "APPROVE", "analysis_id": "nope"})[0] == 404

def test_input_validation_and_routing():
    app, _ = make_app()
    assert call(app, "POST", "/analyze", {}, {"mode": "weird"})[0] == 400
    assert call(app, "POST", "/analyze", {}, {"replay_aqi": 9999})[0] == 400
    assert call(app, "POST", "/analyze", {}, {"replay_aqi": "238"})[0] == 400
    assert call(app, "POST", "/analyze", {}, {"school_id": "missing-school"})[0] == 404
    assert call(app, "GET", "/analyze")[0] == 405 and call(app, "GET", "/nope")[0] == 404
    assert call(app, "GET", "/history", {"limit": "abc"})[0] == 400
    assert call(app, "GET", "/daily-plan")[0] == 404                      # nothing analyzed yet
    assert call(app, "GET", "/school")[1]["name"] == "Green Valley Public School"
    assert len(call(app, "GET", "/zones")[1]["zones"]) == 5 and call(app, "GET", "/activities")[1]["activities"][0]["time"] == "09:00"

def test_good_air_via_api_makes_no_changes():
    a = analyze_ok(make_app()[0], replay_aqi=40)
    assert all(p["action"] == "KEEP" for p in a["plan"]) and a["environment"]["pm25"] is None

def test_unexpected_error_does_not_leak():
    app, repo = make_app(); repo.s = None            # break storage
    st, out = call(app, "POST", "/analyze", {}, {})
    assert st == 500 and out["error"]["code"] == "INTERNAL_ERROR" and out["request_id"] and "Attribute" not in json.dumps(out)

# ---------- providers / trust / failure modes ----------
def test_live_unconfigured_returns_unavailable_never_fabricates():
    app, _ = make_app(settings=Settings(environment_provider="live"))
    a = analyze_ok(app)
    assert a["environment"]["status"] == "UNAVAILABLE" and a["plan"] == [] and a["impact"] is None
    assert {w["code"] for w in a["warnings"]} >= {"NO_ENV_DATA", "PROVIDER"}
    assert call(app, "POST", "/decisions", {}, {"analysis_id": a["analysis_id"], "activity_id": "a1", "decision": "APPROVE", "admin": "x"})[0] == 409
    assert call(app, "GET", "/history")[1]["history"][0]["final_index"] is None

def raw(minutes_old, pm25=100): return {"pm25": pm25, "observed_at": (NOW - timedelta(minutes=minutes_old)).isoformat(), "source": "SRC", "station": "ST"}

def test_live_provider_success_and_trust_fields():
    app, _ = make_app(live=LiveProvider("http://x", "k", fetch=lambda u, h, t: raw(10)))
    e = analyze_ok(app, mode="LIVE")["environment"]
    assert e["mode"] == "LIVE" and e["quality"] == "DERIVED" and e["retrieved_at"] and e["observed_at"] and e["status"] == "FRESH"
    assert e["label"] == "LIVE \u2014 SRC \u2014 updated 10 min ago"

def test_api_failure_uses_last_trusted_snapshot_then_unavailable():
    calls = {"ok": True}
    def fetch(u, h, t):
        if calls["ok"]: return raw(10)
        raise TimeoutError("secret-key-in-url")
    app, _ = make_app(live=LiveProvider("http://x", "k", fetch=fetch)); analyze_ok(app, mode="LIVE")
    calls["ok"] = False
    b = analyze_ok(app, mode="LIVE")                                   # last trusted (10 min old) still acceptable
    assert b["environment"]["quality"] == "DEGRADED" and any(w["code"] == "DEGRADED_DATA" for w in b["warnings"])
    assert "secret-key" not in json.dumps(b)                           # exception text never leaks
    app.clock = lambda: NOW + timedelta(hours=4)                       # last trusted is now too old
    assert analyze_ok(app, mode="LIVE")["environment"]["status"] == "UNAVAILABLE"

def test_live_provider_rejects_garbage_and_bad_timestamp():
    assert LiveProvider("http://x", "k", fetch=lambda *a: {"nonsense": 1}).get_snapshot(NOW).snapshot is None
    assert LiveProvider("http://x", "k", fetch=lambda *a: raw(-120)).get_snapshot(NOW).snapshot is None   # future

def test_stale_data_warns_and_lowers_confidence():
    a = analyze(seed.ACTIVITIES, seed.ZONES, seed.demo_snapshot(NOW, 238, 300), NOW, *seed.DAY)
    assert any(w["code"] == "STALE_DATA" for w in a["warnings"]) and {p["confidence"] for p in a["plan"]} == {"Low"}

def test_ai_fallback_warning_only_when_ai_attempted():
    plain = analyze(seed.ACTIVITIES, seed.ZONES, seed.demo_snapshot(NOW), NOW, *seed.DAY)
    assert plain["warnings"] == []
    class Boom:
        def converse(self, **k): raise TimeoutError()
    app, _ = make_app(planner=BedrockPlanner(Boom(), "m"))
    a = analyze_ok(app)
    assert a["ai"]["used_fallback"] and any(w["code"] == "AI_FALLBACK" for w in a["warnings"])
    assert a["impact"]["proposed_index"] == 60.1                       # workflow unaffected

# ---------- locked AI schema guardrails ----------
def cands_ctx():
    from breatheops.ai import build_context
    from breatheops.trust import freshness
    zm = {z.zone_id: z for z in seed.ZONES}
    c = {a.activity_id: generate(a, seed.ACTIVITIES, seed.ZONES, lambda m: 238.0, *seed.DAY) for a in seed.ACTIVITIES}
    base = analyze(seed.ACTIVITIES, seed.ZONES, seed.demo_snapshot(NOW), NOW, *seed.DAY)
    risk = {b["activity_id"]: (b["dose"], b["risk"]) for b in base["risk_board"]}
    return c, build_context(seed.demo_snapshot(NOW), freshness(NOW, NOW), seed.ACTIVITIES, zm, risk, c), base

def good_rec(base, aid):
    p = next(x for x in base["plan"] if x["activity_id"] == aid)
    return {"activity_id": aid, "action": p["action"], "reason": "ok", "evidence": ["AQI 238 (Poor)"],
            "confidence": "High", "modeled_impact": p["modeled_impact"]}

@pytest.mark.parametrize("mutate,expect", [
    (lambda r: r.update(reason="Sports at 60 min raises 73% of asthma risk"), "medical"),
    (lambda r: r.update(reason="Cuts exposure by 73 percent"), "not found in provided data"),
    (lambda r: r.update(evidence=[]), "evidence"),
    (lambda r: r.update(evidence=["x"] * 5), "evidence"),
    (lambda r: r.update(modeled_impact={"before": 1, "after": 0}), "does not match the engine"),
    (lambda r: r.pop("modeled_impact"), "modeled_impact"),
    (lambda r: r.update(confidence="Certain"), "confidence"),
    (lambda r: r.update(reason="x" * 401), "too long"),
])
def test_ai_schema_rejections(mutate, expect):
    c, ctx, base = cands_ctx()
    recs = [good_rec(base, a.activity_id) for a in seed.ACTIVITIES]
    mutate(recs[2])
    ok, errs = validate_ai_output({"recommendations": recs}, c, ctx)
    assert not ok and any(expect in e for e in errs), errs

def test_ai_grounded_numbers_and_rounding_accepted():
    c, ctx, base = cands_ctx()
    recs = [good_rec(base, a.activity_id) for a in seed.ACTIVITIES]
    recs[2]["reason"] = "At AQI 238 a 60 min session scores 55.7 and 30 min scores 27.8."   # rounded from 55.68 / 27.84
    assert validate_ai_output({"recommendations": recs}, c, ctx) == (True, [])

# ---------- repository / DynamoDB ----------
class FakeCCF(Exception):
    response = {"Error": {"Code": "ConditionalCheckFailedException"}}


class FakeTable:
    """Mimics boto3 Table: rejects floats like real DynamoDB, supports the exact query shape we use."""
    def __init__(self): self.rows = {}
    def _check(self, v):
        if isinstance(v, float): raise TypeError("Float types are not supported. Use Decimal types instead")
        if isinstance(v, dict): [self._check(x) for x in v.values()]
        if isinstance(v, list): [self._check(x) for x in v]
    def put_item(self, Item, ConditionExpression=None):
        self._check(Item)
        if ConditionExpression and (Item["pk"], Item["sk"]) in self.rows: raise FakeCCF()
        self.rows[(Item["pk"], Item["sk"])] = Item
    def get_item(self, Key):
        r = self.rows.get((Key["pk"], Key["sk"])); return {"Item": r} if r else {}
    def query(self, KeyConditionExpression, ExpressionAttributeValues, ScanIndexForward=True, Limit=None, ExclusiveStartKey=None):
        pk, pre = ExpressionAttributeValues[":pk"], ExpressionAttributeValues[":p"]
        rows = sorted((k for k in self.rows if k[0] == pk and k[1].startswith(pre)), reverse=not ScanIndexForward)
        return {"Items": [self.rows[k] for k in rows[:Limit]]}

def test_dynamo_roundtrip_floats_and_full_workflow():
    repo = Repository(DynamoStore(FakeTable())); seed.seed_repository(repo)
    app = App(Settings(), repo, clock=lambda: NOW)
    a = analyze_ok(app)
    stored = repo.get_analysis("demo-school", a["analysis_id"])
    assert stored == json.loads(json.dumps(a))                          # float -> Decimal -> float is lossless
    assert call(app, "POST", "/decisions", {}, {"analysis_id": a["analysis_id"], "activity_id": "a1", "decision": "APPROVE", "admin": "x"})[0] == 200
    assert len(call(app, "GET", "/history")[1]["history"]) == 1
    assert [x.activity_id for x in repo.list_activities("demo-school")] == ["a1", "a2", "a3", "a4", "a5"]
    assert repo.list_zones("demo-school")[0].supports.__class__ is frozenset

def test_ddb_conversion_helpers():
    assert to_ddb({"a": [1.5, {"b": 2}]}) == {"a": [Decimal("1.5"), {"b": 2}]}
    assert from_ddb({"a": Decimal("2"), "b": Decimal("2.5")}) == {"a": 2, "b": 2.5}

def test_history_newest_first_and_school_isolation():
    app, repo = make_app(); t = {"now": NOW}
    app.clock = lambda: t["now"]
    ids = []
    for i in range(3):
        t["now"] = NOW + timedelta(minutes=i); ids.append(analyze_ok(app)["analysis_id"])
    assert [h["analysis_id"] for h in call(app, "GET", "/history")[1]["history"]] == ids[::-1]
    repo.put_school("other-school", seed.SCHOOL)
    assert call(app, "GET", "/history", {"school_id": "other-school"})[1]["history"] == []

# ---------- config / security / handler ----------
def test_settings_never_print_key():
    s = Settings.from_env({"ENVIRONMENT_API_KEY": "SECRET123", "ADMIN_TOKEN": "TOKEN-TOKEN-TOKEN-1"})
    assert "SECRET123" not in repr(s) and "TOKEN-TOKEN" not in repr(s)

def test_no_secrets_in_repo():
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
    import re
    pat = re.compile(r"AKIA[0-9A-Z]{16}|aws_secret_access_key\s*=\s*\S+|sk-[A-Za-z0-9]{20,}", re.I)
    for d, _, fs in os.walk(root):
        if any(x in d.split(os.sep) for x in (".git", "__pycache__", ".pytest_cache", ".venv", ".venv312", "site-packages", ".aws-sam")): continue
        for f in fs:
            if f.endswith((".py", ".md", ".yaml", ".json", ".example")):
                assert not pat.search(open(os.path.join(d, f), encoding="utf-8").read()), f
    assert os.path.exists(os.path.join(root, ".env.example")) and ".env" in open(os.path.join(root, ".gitignore")).read()

def test_lambda_handler_http_api_v2(monkeypatch):
    import breatheops.handler as h
    monkeypatch.delenv("TABLE", raising=False); monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False); h._app = None
    ev = lambda m, p, body=None, q=None: {"requestContext": {"http": {"method": m}}, "rawPath": p, "body": body, "queryStringParameters": q}
    r = h.lambda_handler(ev("POST", "/analyze", json.dumps({"replay_aqi": 238})))
    assert r["statusCode"] == 200 and json.loads(r["body"])["data"]["environment"]["aqi"] == 238
    assert h.lambda_handler(ev("POST", "/analyze", "{bad"))["statusCode"] == 400
    assert h.lambda_handler(ev("POST", "/analyze", "x" * 25_000))["statusCode"] == 413
    b64 = base64.b64encode(json.dumps({"replay_aqi": 120}).encode()).decode()
    assert h.lambda_handler({**ev("POST", "/analyze", b64), "isBase64Encoded": True})["statusCode"] == 200
    assert h.lambda_handler(ev("GET", "/history"))["statusCode"] == 200

# ---------- exposure edge cases (documented) ----------
def test_exposure_edge_cases():
    assert severity(-20) == 0 and severity(750) == 1.0
    assert index_vs_baseline(0.0, 0.0) == (100.0, 0.0)
    all_indoor = [a for a in seed.ACTIVITIES if a.zone_id in ("main", "cafe")]
    r = analyze(all_indoor, seed.ZONES, seed.demo_snapshot(NOW, 0), NOW, *seed.DAY)
    assert r["impact"]["pct_lower"] == 0 and all(p["action"] == "KEEP" for p in r["plan"])
