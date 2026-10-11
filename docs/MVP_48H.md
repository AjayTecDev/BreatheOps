# 48-hour MVP cut

**One user, one problem, one workflow:** school admin -> air quality -> schedule decisions.

## Build (in order)
1. [done] Engine, candidates, guardrails, locked AI schema, providers, DynamoDB repository, API, audit trail (86 tests)
2. Deploy SAM stack; Lambda returns replay analysis via API Gateway
3. Seed school/zones/timetable into DynamoDB (hardcoded school, no setup forms)
4. Real AQI ingestion (CPCB/OpenAQ). First check a station exists near Bidar; otherwise keep REPLAY, labeled in the UI
5. Bedrock call: prompt = snapshot + risk board + candidates -> JSON schema; fallback already wired
6. Frontend: Dashboard -> Analyze -> Risk board -> Plan + Why panel -> Approve/Modify/Reject -> Impact
7. Save decisions + Daily Plan + History (simple list)

## Cut / defer
Setup forms, auth, What-if simulator, alerts, PDF export, multi-school, Strands (only if it earns its place), RESTRICT action.

## Rules
- Freeze the exposure formula now; don't retune it to hit a demo number.
- Every UI recommendation shows source, freshness, confidence and the modeled before/after.
- Demo data is labeled REPLAY; real data is labeled with station + age.
