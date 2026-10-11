# Frontend architecture (API-driven)

The UI never computes AQI, risk, exposure, impact or recommendations. It calls the API, renders `data`, and switches on `error.code`.
The published prototype (`frontend/breatheops-app.html`) still runs on the canonical demo fixture; the next step is replacing its data layer with the client below.

```
frontend/
  api client   request(method, path, body) -> {success, data|error}; adds Authorization + X-Admin-Name; keeps request_id
  state        analysis, decisions (from API responses), loading/error flags per action
  screens      Landing, Dashboard, Risk Board, Plan My Day, Recommendation + Why, Approval, Impact, Daily Plan, History, Settings (read-only school/zones/activities + disclaimer)
```
Base URL: `http://localhost:8787` (`backend/local_server.py`) -> API Gateway URL later.

| Action | Call |
|---|---|
| Plan my day | `POST /analyze` |
| Approve / Modify / Reject | `POST /decisions` (Modify sends an option's `modification`) |
| Impact | `impact` from the last `POST /decisions`, or the analysis' proposed index |
| Daily plan / History | `GET /daily-plan`, `GET /history` |

## States every action needs
Loading (single spinner; only show step text that reflects real phases) / Success / Error (map `error.code` to a plain sentence, show request id) / Empty / Degraded.
Degraded = any `warnings`: banner text from the API; `DEGRADED_DATA`, `STALE_DATA`, `AI_FALLBACK` ("Rule-based planning is active") each get a calm, non-technical message.
`UNAVAILABLE` environment: "Environmental data temporarily unavailable", show last trusted reading time if present, no recommendations.
`UNAUTHORIZED`: return to the admin sign-in.
