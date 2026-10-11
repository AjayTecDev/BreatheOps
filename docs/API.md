# API (HTTP API v2)

Every response: success `{"success": true, "data": {...}, "request_id": "..."}`; error `{"success": false, "error": {"code": "...", "message": "..."}, "request_id": "..."}`.
Headers: `Authorization: Bearer <token>` (when `AUTH_MODE=token`), `X-Admin-Name: <label>` (audit display name), response `X-Request-Id`. `school_id` defaults to `demo-school`.

| Method + path | Purpose |
|---|---|
| `POST /analyze` `{school_id?, mode?: REPLAY\|LIVE, replay_aqi?: 0-500}` | Run Plan My Day. Stores and returns the analysis. |
| `GET /school`, `/zones`, `/activities` | Campus data. |
| `POST /decisions` `{analysis_id, activity_id, decision: APPROVE\|MODIFY\|REJECT, note?, modification?: {zone_id?, start?: "HH:MM", duration?}}` | Append-only audit record. `modification` is required for MODIFY and is validated. Returns `{decision, impact}`. |
| `GET /history?limit=10` | Past analyses with counts and final index. |
| `GET /daily-plan?analysis_id?` | Operational plan (latest if no id). |

## Error codes
`INVALID_REQUEST` 400/422, `UNAUTHORIZED` 401, `NOT_FOUND` 404, `METHOD_NOT_ALLOWED` 405, `NO_TIMETABLE` 409, `ENVIRONMENT_UNAVAILABLE` 409,
`PAYLOAD_TOO_LARGE` 413, `INFEASIBLE_MODIFICATION` 422, `INTERNAL_ERROR` 500 (request id only).

## Analysis object (full real example: `canonical_demo.json`; the stored version adds ids)
`analysis_id, plan_id, school_id, created_at`
`environment {aqi, category, pm25, source, station, mode, snapshot_id, label, observed_at, retrieved_at, status, age_minutes, quality, confidence}`
`risk_board [{activity_id, name, time, duration, zone, setting, dose, risk}]`
`plan [{activity_id, recommendation_id, action, priority, detail, reason, evidence[], confidence, modeled_impact{before, after}, new_start, new_duration, new_zone, options[]}]`
`options[]` are every feasible alternative: `{action, detail, modeled_after, new_start, new_duration, new_zone, modification{zone_id, start, duration}}`; POST `modification` as-is to modify.
`impact {baseline_index, proposed_index, pct_lower, label}` or null | `ai {attempted, used_fallback, planner, validation_errors[], error}`
`warnings [{code, message}]`: STALE_DATA, AGING_DATA, DEGRADED_DATA, DERIVED_AQI, AI_FALLBACK, NO_ENV_DATA, PROVIDER.
Trust fields: mode LIVE|REPLAY; status FRESH <=60 min / AGING <=180 / STALE / UNAVAILABLE; quality OK (reported) | DERIVED (from PM2.5) | DEGRADED (last trusted reading); confidence High|Medium|Low.

## Decision record
`decision_id, analysis_id, recommendation_id, activity_id, decision, decided_by, decided_by_id, decided_at, seq, supersedes, note, original_recommendation{...}, final{...}`.
Records are never edited; a newer decision for the same activity points to the one it supersedes, and the latest wins in plan/impact/history.
