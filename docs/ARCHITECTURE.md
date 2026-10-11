# Architecture

## Layers (dependencies point down; tests enforce the boundaries)
```
Frontend (API client only: GET/POST/render, never computes AQI, risk, exposure or impact)
   |  HTTPS + JSON envelope
API Gateway (CORS, throttling)
   |
handler.py     parse event, correlation id, respond                      (thin)
api.py         routing, request validation, auth, {success,data|error}   (transport)
services.py    Analyze / Decision / History / DailyPlan / Campus         (application)
   |-- providers.py + ingest.py + trust.py   Replay | Live | Resilient -> normalized Snapshot
   |-- analyze.py -> exposure.py, candidates.py, planner.py              (pure domain, no I/O)
   |-- ai.py         BedrockPlanner | DeterministicPlanner
   |-- decisions.py  decision records, daily plan, history views
   '-- repository.py MemoryRepository | DynamoRepository (same contract)
```
The exposure engine receives a normalized `Snapshot` and cannot tell whether it came from CPCB, OpenAQ or replay.
Only `config.py` reads environment variables.

## Data flow (one Analyze request)
1. `POST /analyze` -> auth -> validation -> `AnalyzeService.run`
2. Provider returns a `Snapshot` (REPLAY, or LIVE -> last trusted reading -> unavailable). The snapshot is stored with a `snapshot_id`.
3. Trust layer: freshness, confidence, quality (reported / derived / degraded).
4. Exposure engine -> risk board -> feasible action candidates (capacity, zone support, hours, forecast).
5. Planner: Bedrock ranks candidates **if configured**; output is validated; any failure -> deterministic plan.
6. Analysis (with `analysis_id`, `plan_id`, per-activity `recommendation_id`, `options`) is stored and returned.
7. `POST /decisions`: Approve / Modify (validated) / Reject -> append-only decision record -> updated impact.
8. `GET /daily-plan`, `GET /history` are views over analyses + decisions.

## Entities (every one has an id)
| Entity | Id | Stored as |
|---|---|---|
| School, Zone, Activity | `school_id`, `zone_id`, `activity_id` | `SCHOOL#id` / `META`, `ZONE#id`, `ACTIVITY#id` |
| EnvironmentSnapshot | `snapshot_id` | `SNAPSHOT#id` (immutable) |
| Analysis | `analysis_id` (time-sortable) | `ANALYSIS#id` (immutable) |
| Recommendation | `recommendation_id` = `<analysis_id>.<activity_id>` | embedded in the analysis (no separate table) |
| Decision | `decision_id` | `DECISION#<analysis_id>#<decision_id>` (append-only, `seq`, `supersedes`) |
| DailyPlan | `plan_id` = `plan-<analysis_id>` | derived view, not stored |

## Fallback matrix
| Failure | Behavior |
|---|---|
| Live source down | last trusted LIVE reading if <= 3 h old (quality DEGRADED, warning), else UNAVAILABLE: timetable shown, no recommendations |
| Stale/aging data | warning + lower confidence; AI confidence is capped at the data's confidence |
| No Bedrock configured / timeout / bad JSON / infeasible or invented content | deterministic plan, `AI_FALLBACK` warning |
| No indoor zone / no capacity / no forecast | candidate not offered; explanation stays honest |
| Unexpected error | `INTERNAL_ERROR` with a request id; no internals leaked |

## AWS (minimal)
API Gateway HTTP API -> Lambda (`ApiFn`) -> DynamoDB (single table) + Bedrock (Converse) -> CloudWatch (structured JSON logs, error alarm).
S3 is intentionally unused until PDF export exists. Template: `infra/template.yaml` (not yet deployed).

## Deployment
Config via environment variables (see `.env.example`); `APP_ENV=production` refuses to start without TABLE, token auth and an https origin.
Steps are in README. Secrets belong in SSM SecureString / Secrets Manager, never in Git.
