import sys, os, json, ast, glob
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
from datetime import datetime, timedelta
import pytest
from test_platform import FakeTable
from breatheops import seed
from breatheops.api import App
from breatheops.ai import BedrockPlanner
from breatheops.auth import build_auth
from breatheops.config import ConfigError, Settings
from breatheops.models import Activity, Snapshot, Zone, hm
from breatheops.observability import RequestLog
from breatheops.providers import LiveProvider
from breatheops.repository import DuplicateError, DynamoRepository, MemoryRepository, RepositoryAPI

NOW = datetime(2026, 10, 10, 8, 40)
SRC = os.path.join(HERE, "..", "src", "breatheops")


def make(settings=None, planner=None, live=None, repo=None, sink=None, clock=NOW):
    repo = repo or MemoryRepository(); seed.seed_repository(repo)
    return App(settings or Settings(), repo, planner, live, lambda: clock, sink or (lambda e: None)), repo

def post(app, path, body, headers=None): return app.handle("POST", path, {}, body, headers)

# ---------------- response envelope + error codes ----------------
def test_envelope_shapes_and_error_codes():
    app, repo = make()
    st, env = app.handle("GET", "/school")
    assert (st, env["success"]) == (200, True) and env["data"]["name"] and env["request_id"]
    st, env = app.handle("GET", "/nope")
    assert env == {"success": False, "error": {"code": "NOT_FOUND", "message": "not found"}, "request_id": env["request_id"]}
    assert app.handle("GET", "/analyze")[1]["error"]["code"] == "METHOD_NOT_ALLOWED"
    assert post(app, "/analyze", {"mode": "x"})[1]["error"]["code"] == "INVALID_REQUEST"
    assert post(app, "/analyze", [1, 2])[0] == 400                                   # body must be an object
    repo.put_school("empty-school", seed.SCHOOL)
    assert post(app, "/analyze", {"school_id": "empty-school"})[1]["error"]["code"] == "NO_TIMETABLE"
    a = post(app, "/analyze", {})[1]["data"]
    mod = lambda m: post(app, "/decisions", {"analysis_id": a["analysis_id"], "activity_id": "a3", "decision": "MODIFY", "modification": m})
    assert mod({"duration": 99})[1]["error"]["code"] == "INFEASIBLE_MODIFICATION"
    assert post(app, "/decisions", {"analysis_id": a["analysis_id"], "activity_id": "zzz", "decision": "APPROVE"})[0] == 404
    assert post(app, "/decisions", {"analysis_id": a["analysis_id"], "activity_id": "a3", "decision": "MODIFY"})[0] == 400   # needs modification
    assert post(app, "/decisions", {"analysis_id": a["analysis_id"], "activity_id": "a3", "decision": "APPROVE", "modification": {"duration": 30}})[0] == 400
    app2, _ = make(Settings(environment_provider="live"))
    a2 = post(app2, "/analyze", {})[1]["data"]
    assert post(app2, "/decisions", {"analysis_id": a2["analysis_id"], "activity_id": "a1", "decision": "APPROVE"})[1]["error"]["code"] == "ENVIRONMENT_UNAVAILABLE"

# ---------------- auth ----------------
def test_token_auth_protects_every_route_and_attributes_decisions():
    tok = "t" * 24
    app, _ = make(Settings(auth_mode="token", admin_token=tok))
    for m, p in (("GET", "/school"), ("POST", "/analyze"), ("GET", "/history"), ("POST", "/decisions")):
        st, env = app.handle(m, p, {}, {} if m == "POST" else None)
        assert (st, env["error"]["code"]) == (401, "UNAUTHORIZED")
    assert app.handle("GET", "/school", {}, None, {"Authorization": "Bearer wrong"})[0] == 401
    assert app.handle("GET", "/school", {}, None, {"Authorization": tok})[0] == 401            # scheme required
    ok = {"Authorization": f"Bearer {tok}", "X-Admin-Name": "Ms.\x00 Rao" + "x" * 80}
    a = post(app, "/analyze", {}, ok)[1]["data"]
    d = post(app, "/decisions", {"analysis_id": a["analysis_id"], "activity_id": "a3", "decision": "APPROVE", "admin": "Hacker"}, ok)[1]["data"]["decision"]
    assert d["decided_by_id"] == "admin" and d["decided_by"].startswith("Ms. Raox") and len(d["decided_by"]) <= 60 and "Hacker" not in json.dumps(d)

def test_demo_auth_defaults_and_production_refuses_it():
    app, _ = make()
    a = post(app, "/analyze", {})[1]["data"]
    d = post(app, "/decisions", {"analysis_id": a["analysis_id"], "activity_id": "a3", "decision": "APPROVE", "admin": "Hacker"})[1]["data"]["decision"]
    assert d["decided_by"] == "DEMO_ADMIN"                                                     # body never decides identity
    with pytest.raises(ConfigError): Settings.load({"APP_ENV": "production"})
    assert build_auth(Settings(auth_mode="token", admin_token="x" * 20)).__class__.__name__ == "TokenAuthService"

# ---------------- configuration ----------------
def test_config_validation():
    s = Settings.load({}); assert (s.environment_provider, s.ai_enabled) == ("replay", False)  # replay needs no credentials
    with pytest.raises(ConfigError) as e: Settings.load({"ENVIRONMENT_PROVIDER": "live"})
    assert "ENVIRONMENT_API_URL" in str(e.value) and "ENVIRONMENT_API_KEY" in str(e.value)
    assert Settings.load({"ENVIRONMENT_PROVIDER": "LIVE", "ENVIRONMENT_API_URL": "https://x", "ENVIRONMENT_API_KEY": "SECRETVAL"}).environment_provider == "live"
    with pytest.raises(ConfigError) as e: Settings.load({"AUTH_MODE": "token", "ADMIN_TOKEN": "TOKENVALUE"})
    assert "ADMIN_TOKEN" in str(e.value) and "TOKENVALUE" not in str(e.value)
    with pytest.raises(ConfigError): Settings.load({"ENVIRONMENT_PROVIDER": "bogus"})
    with pytest.raises(ConfigError) as e: Settings.load({"APP_ENV": "production"})
    assert all(k in str(e.value) for k in ("TABLE", "AUTH_MODE", "ALLOWED_ORIGIN"))
    prod = {"APP_ENV": "production", "TABLE": "t", "AUTH_MODE": "token", "ADMIN_TOKEN": "x" * 20, "ALLOWED_ORIGIN": "https://app.example.org"}
    assert Settings.load(prod).app_env == "production"
    with pytest.raises(ConfigError): Settings.load({**prod, "ALLOWED_ORIGIN": "*"})
    assert Settings.load({"BEDROCK_MODEL_ID": "m"}).ai_enabled

# ---------------- domain validation ----------------
@pytest.mark.parametrize("kw", [{"duration": -5}, {"duration": 0}, {"duration": 999}, {"occupancy": -1}, {"start": 2000},
                                {"intensity": "extreme"}, {"activity_id": "bad id"}, {"zone_id": ""}, {"name": " "}])
def test_activity_rejects_invalid_values(kw):
    base = dict(activity_id="x1", name="N", kind="class", start=540, duration=30, zone_id="main", occupancy=10, intensity="light")
    with pytest.raises(ValueError): Activity(**{**base, **kw})

def test_zone_and_time_validation():
    with pytest.raises(ValueError): Zone("z", "Z", True, 0, frozenset())
    with pytest.raises(ValueError): Zone("bad id", "Z", True, 5, frozenset())
    for bad in ("25:00", "9:00", "09:60", "", None): 
        with pytest.raises(ValueError): hm(bad)
    assert hm("09:30") == 570

# ---------------- repository parity ----------------
def snap(i="snap-1", mode="LIVE", q="OK", mins=10):
    return Snapshot(100.0, 80.5, "S", "ST", NOW - timedelta(minutes=mins), mode, NOW, q, i)

@pytest.fixture(params=["memory", "dynamo"])
def repo(request):
    return MemoryRepository() if request.param == "memory" else DynamoRepository(FakeTable())

def test_both_repositories_expose_identical_operations():
    pub = lambda c: {n for n in dir(c) if not n.startswith("_") and callable(getattr(c, n))}
    contract = {n for n in dir(RepositoryAPI) if not n.startswith("_")}
    assert pub(MemoryRepository) == pub(DynamoRepository) and contract <= pub(MemoryRepository)

def test_repository_contract(repo):
    seed.seed_repository(repo, "demo-school")
    assert repo.get_school("demo-school")["name"] == seed.SCHOOL["name"] and repo.get_school("nope") is None
    assert set(repo.list_zones("demo-school")) == set(seed.ZONES)
    assert repo.list_activities("demo-school") == list(seed.ACTIVITIES)
    repo.save_snapshot("demo-school", snap("snap-a", "LIVE", mins=30)); repo.save_snapshot("demo-school", snap("snap-b", "LIVE", "DEGRADED", 5))
    repo.save_snapshot("demo-school", snap("snap-c", "REPLAY", mins=1))
    assert repo.latest_snapshot("demo-school", "LIVE") == snap("snap-a", "LIVE", mins=30)      # skips DEGRADED and REPLAY
    assert repo.latest_snapshot("demo-school", "REPLAY").snapshot_id == "snap-c" and repo.latest_snapshot("other", "LIVE") is None
    with pytest.raises(DuplicateError): repo.save_snapshot("demo-school", snap("snap-a"))      # immutable
    an = {"analysis_id": "20261010T084000-aaaaaa", "environment": {"aqi": 238.5}, "plan": []}
    repo.save_analysis("demo-school", an)
    with pytest.raises(DuplicateError): repo.save_analysis("demo-school", an)
    assert repo.get_analysis("demo-school", an["analysis_id"]) == an
    for i, seq in ((1, 2), (2, 1)):                                                            # same timestamp: seq orders
        repo.save_decision("demo-school", {"analysis_id": "A1", "decision_id": f"d{i}", "decided_at": "2026-10-10T08:40:00", "seq": seq})
    assert [d["decision_id"] for d in repo.list_decisions("demo-school", "A1")] == ["d2", "d1"]
    with pytest.raises(DuplicateError): repo.save_decision("demo-school", {"analysis_id": "A1", "decision_id": "d1", "decided_at": "x"})
    assert repo.list_decisions("demo-school", "A2") == []

# ---------------- ids + audit trail ----------------
def test_entities_have_ids_and_snapshot_is_persisted():
    app, repo = make()
    a = post(app, "/analyze", {})[1]["data"]
    recs = [p["recommendation_id"] for p in a["plan"]]
    assert len(set(recs)) == 5 and all(r.startswith(a["analysis_id"]) for r in recs) and a["plan_id"] == f"plan-{a['analysis_id']}"
    assert repo.latest_snapshot("demo-school", "REPLAY").snapshot_id == a["environment"]["snapshot_id"]
    assert app.handle("GET", "/daily-plan")[1]["data"]["plan_id"] == a["plan_id"]

def test_decisions_are_append_only_with_supersedes_chain():
    app, repo = make(); a = post(app, "/analyze", {})[1]["data"]
    base = {"analysis_id": a["analysis_id"], "activity_id": "a3"}
    d1 = post(app, "/decisions", {**base, "decision": "APPROVE"})[1]["data"]["decision"]
    d2 = post(app, "/decisions", {**base, "decision": "MODIFY", "modification": {"duration": 45}, "note": "inter-school event"})[1]["data"]["decision"]
    d3 = post(app, "/decisions", {**base, "decision": "REJECT"})[1]["data"]
    stored = repo.list_decisions("demo-school", a["analysis_id"])
    assert [x["decision_id"] for x in stored] == [d1["decision_id"], d2["decision_id"], d3["decision"]["decision_id"]]
    assert (d1["supersedes"], d2["supersedes"], d3["decision"]["supersedes"]) == (None, d1["decision_id"], d2["decision_id"])
    assert [x["seq"] for x in stored] == [1, 2, 3] and d2["original_recommendation"]["new_duration"] == 30 and d2["final"]["new_duration"] == 45
    assert d2["recommendation_id"] == a["plan"][2]["recommendation_id"] and d3["impact"]["final_index"] == 100.0   # latest wins; earlier rows untouched
    assert stored[0]["final"]["new_duration"] == 30

def test_every_offered_option_is_accepted_by_the_api():
    app, _ = make(); a = post(app, "/analyze", {})[1]["data"]
    n = 0
    for p in a["plan"]:
        for o in p["options"]:
            st, env = post(app, "/decisions", {"analysis_id": a["analysis_id"], "activity_id": p["activity_id"], "decision": "MODIFY", "modification": o["modification"]})
            assert st == 200, (p["activity_id"], o)
            assert env["data"]["decision"]["final"]["modeled_dose_after"] == pytest.approx(o["modeled_after"], abs=0.011); n += 1
    assert n >= 10
    a1 = next(p for p in a["plan"] if p["activity_id"] == "a1")
    assert {"KEEP", "MOVE_INDOORS", "SHORTEN", "MONITOR"} == {o["action"] for o in a1["options"]}

# ---------------- observability ----------------
def test_logs_are_structured_correlated_and_free_of_secrets():
    logs = []
    def fetch(u, h, t): raise ConnectionError("boom SECRETKEY123 in url")
    app, _ = make(Settings(environment_provider="live"), live=LiveProvider("https://x", "SECRETKEY123", fetch=fetch), sink=logs.append)
    st, env = app.handle("POST", "/analyze", {}, {}, None, "req-123")
    assert env["request_id"] == "req-123" and logs and all(e["request_id"] == "req-123" for e in logs)
    assert [e["event"] for e in logs] == ["analysis_started", "environment_fetch", "provider_failure", "analysis_completed", "request_completed"]
    assert "SECRETKEY123" not in json.dumps(logs) and logs[-1]["status"] == 200 and "ms" in logs[-1]
    out = []; RequestLog(out.append, "r").event("x", api_key="abc", Authorization="Bearer z", note="ok")
    assert out[0]["api_key"] == out[0]["Authorization"] == "[redacted]" and out[0]["note"] == "ok"

class FakeBedrock:
    def __init__(self, mode="ok"): self.mode = mode
    def converse(self, **kw):
        if self.mode == "timeout": raise TimeoutError("slow")
        ctx = json.loads(kw["messages"][0]["content"][0]["text"])
        recs = []
        for a in ctx["activities"]:
            best = min(a["feasible_actions"], key=lambda f: f["modeled_dose_after"])
            recs.append({"activity_id": a["activity_id"], "action": best["action"], "reason": "Lowest modeled exposure among feasible actions.",
                         "evidence": [f"AQI {round(ctx['environment']['aqi'])} ({ctx['environment']['category']})"], "confidence": "High",
                         "modeled_impact": {"before": a["modeled_dose"], "after": best["modeled_dose_after"]}})
        if self.mode == "invent": recs[0]["reason"] = "Cuts exposure by 83 percent."
        return {"output": {"message": {"content": [{"text": json.dumps({"recommendations": recs})}]}}}

@pytest.mark.parametrize("mode,fallback,events", [("ok", False, ["ai_requested"]), ("timeout", True, ["ai_requested", "ai_fallback"]), ("invent", True, ["ai_requested", "ai_fallback"])])
def test_ai_events_and_fallback(mode, fallback, events):
    logs = []; app, _ = make(planner=BedrockPlanner(FakeBedrock(mode), "m"), sink=logs.append)
    a = post(app, "/analyze", {})[1]["data"]
    assert a["ai"]["used_fallback"] is fallback and a["ai"]["planner"] == "bedrock"
    assert [e["event"] for e in logs if e["event"].startswith("ai_")] == events
    assert a["impact"]["proposed_index"] > 0                                                   # workflow always completes

def test_ai_is_optional_deterministic_when_unconfigured():
    logs = []; app, _ = make(sink=logs.append); a = post(app, "/analyze", {})[1]["data"]
    assert a["ai"]["planner"] == "deterministic" and not a["ai"]["attempted"] and a["warnings"] == [] and not any(e["event"].startswith("ai_") for e in logs)

# ---------------- layer boundaries ----------------
def imports(name):
    tree = ast.parse(open(os.path.join(SRC, name + ".py"), encoding="utf-8").read()); out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.level == 1: out |= {n.module} if n.module else {a.name for a in n.names}
    return out

def test_exposure_engine_never_knows_the_data_source():
    for m in ("exposure", "candidates", "planner", "trust", "models", "analyze"):
        assert not imports(m) & {"providers", "ingest", "repository", "config", "seed", "api", "services", "handler", "auth"}, m

def test_api_and_handler_stay_thin():
    assert not imports("api") & {"analyze", "exposure", "candidates", "decisions", "planner", "repository"}
    assert not imports("handler") & {"analyze", "exposure", "candidates", "decisions", "planner", "services", "providers"}

def test_only_config_reads_environment_variables():
    for f in glob.glob(os.path.join(SRC, "*.py")):
        if os.path.basename(f) != "config.py":
            src = open(f, encoding="utf-8").read(); assert "os.environ" not in src and "getenv" not in src, f

# ---------------- end to end ----------------
def test_end_to_end_live_ai_decisions_plan_history():
    logs, table = [], FakeTable()
    raw = {"pm25": 100, "observed_at": (NOW - timedelta(minutes=10)).isoformat(), "source": "SRC", "station": "ST-1"}
    tok = "e2e-token-" + "x" * 12; H = {"Authorization": f"Bearer {tok}", "X-Admin-Name": "Ms. Rao"}
    app, _ = make(Settings(environment_provider="live", auth_mode="token", admin_token=tok), BedrockPlanner(FakeBedrock(), "m"),
                  LiveProvider("https://x", "k", fetch=lambda *a: raw), DynamoRepository(table), logs.append)
    st, env = app.handle("POST", "/analyze", {}, {"mode": "LIVE"}, H); a = env["data"]
    e = a["environment"]
    assert st == 200 and (e["mode"], e["quality"], e["status"], e["confidence"]) == ("LIVE", "DERIVED", "FRESH", "High") and e["snapshot_id"]
    assert e["label"] == "LIVE \u2014 SRC \u2014 updated 10 min ago" and a["ai"]["used_fallback"] is False
    acts = {p["activity_id"]: p for p in a["plan"]}
    assert acts["a1"]["action"] == "MOVE_INDOORS" and acts["a2"]["action"] == "KEEP"
    d = lambda act, dec, **kw: post(app, "/decisions", {"analysis_id": a["analysis_id"], "activity_id": act, "decision": dec, **kw}, H)
    assert d("a1", "APPROVE")[0] == 200
    assert d("a3", "MODIFY", modification={"duration": 45}, note="inter-school event")[0] == 200
    last = d("a5", "REJECT", note="buses staggered")[1]["data"]
    st, plan = app.handle("GET", "/daily-plan", {"analysis_id": a["analysis_id"]}, None, H); plan = plan["data"]
    assert {i["activity"]: i["status"] for i in plan["items"]}["Sports"] == "MODIFIED" and plan["prepared_by"] == ["Ms. Rao"]
    assert plan["impact"] == last["impact"] and 0 < plan["impact"]["final_index"] < 100
    hist = app.handle("GET", "/history", {}, None, H)[1]["data"]["history"]
    assert len(hist) == 1 and (hist[0]["approved"], hist[0]["modified"], hist[0]["rejected"]) == (1, 1, 1) and hist[0]["mode"] == "LIVE"
    kinds = sorted(k[1].split("#")[0] for k in table.rows if k[1] != "META")
    assert kinds.count("SNAPSHOT") == 1 and kinds.count("ANALYSIS") == 1 and kinds.count("DECISION") == 3
    assert {"analysis_started", "environment_fetch", "ai_requested", "analysis_completed", "decision_created"} <= {x["event"] for x in logs}
    assert app.handle("GET", "/history", {}, None, None)[0] == 401                              # no token, no access
