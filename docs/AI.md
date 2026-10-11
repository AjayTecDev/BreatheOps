# AI design

**Role:** rank feasible actions and explain trade-offs. The AI never computes the index, never sees free-text notes, and is optional.

**Planner interface:** `AIPlanner.rank(context) -> dict | None`. `BedrockPlanner` (Converse API, temperature 0) or `DeterministicPlanner` (returns None = use rules).
Enabled only when `BEDROCK_MODEL_ID` is set. No credentials in code: the Lambda role calls Bedrock.

**What the model sees:** environment (AQI, category, data status/confidence) and, per activity, its risk, modeled dose and the *feasible* actions with their modeled result. Nothing else.

**Locked response schema:** `{"recommendations":[{"activity_id","action","reason","evidence":[...],"confidence","modeled_impact":{"before","after"}}]}`

**Validation (all must pass, else deterministic fallback + `AI_FALLBACK` warning):**
valid JSON -> every activity exactly once -> activity exists -> action is in that activity's feasible set -> `modeled_impact` equals the engine's numbers ->
every number in reason/evidence appears in the supplied data (rounding allowed) -> no medical terms -> length/shape limits.
Confidence is then capped at the data's confidence; displayed numbers always come from the engine.

**Observability:** events `ai_requested`, `ai_fallback` (with rejection count/error type), per-request correlation id.
