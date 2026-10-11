# BreatheOps
*Don't just measure the air. Change what happens because of it.*

Turns air-quality data + a school's real timetable into explainable, feasible, human-approved schedule actions.

## Run it
```bash
pip install pytest
python backend/demo.py                 # AQI 238 replay scenario -> plan + impact
python -m pytest -q backend/tests      # 86 tests
python backend/local_server.py         # full API on http://localhost:8787, no AWS, no keys
```

## Layout
| Path | Role |
|---|---|
| `backend/src/breatheops/` `exposure, candidates, planner, trust, analyze` | pure domain: deterministic exposure, feasible actions, guardrails |
| `providers, ingest` | `EnvironmentProvider`: Replay / Live (placeholder) / Resilient; normalization |
| `ai.py` | `BedrockPlanner` / `DeterministicPlanner` (AI is optional) |
| `services.py` | Analyze / Decision / History / DailyPlan / Campus services |
| `api.py`, `handler.py` | transport + envelope + auth; thin Lambda entrypoint |
| `repository.py` | `MemoryRepository` / `DynamoRepository`, one contract |
| `config.py`, `auth.py`, `observability.py`, `errors.py` | configuration + validation, AuthService, structured logs, error codes |
| `infra/template.yaml` | SAM: HTTP API (CORS, throttle), Lambda, DynamoDB, Bedrock policy, alarm (not deployed) |
| `frontend/` | prototype on fixture data; API client rewrite is next (see `docs/FRONTEND.md`) |
| `docs/` | ARCHITECTURE, EXPOSURE_MODEL, AI, API, SECURITY, THREAT_MODEL, FRONTEND, PITCH, MVP_48H |

## Keys & security
No secrets in the repo. Copy `.env.example` -> `.env` (git-ignored). Replay/local mode needs no credentials. On AWS the Lambda role provides credentials; the source key and admin token go in SSM SecureString / Secrets Manager. `APP_ENV=production` refuses to start without TABLE, token auth and an https origin. See `docs/SECURITY.md` and `docs/THREAT_MODEL.md`.

**Single source of truth for demo numbers:** `docs/canonical_demo.json` (frozen by `backend/freeze_demo.py`). Tests fail if the engine
or `PITCH.md` / `EXPOSURE_MODEL.md` drift from it.

## Deploy checklist (later)
1. Enable a Bedrock model in your region -> `BedrockModelId`; 2. `sam build && sam deploy --guided`; 3. `TABLE=<table> python3 backend/scripts/seed_table.py`;
4. choose the live source -> write its `parser` for `LiveProvider`, set `EnvironmentProvider=live`, `EnvironmentApiUrl/Key`; 5. `AppEnv=production`, `AuthMode=token`, `AdminToken`, `AllowedOrigin`, `BedrockModelArn`; 6. end-to-end test.
