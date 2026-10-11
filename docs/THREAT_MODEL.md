# Threat model (MVP)

| Threat | Impact | Mitigation |
|---|---|---|
| API key / token exposure | Data-source abuse, unauthorized decisions | Env/SSM only, redacted logs, secret scan test, token rotation = redeploy |
| Unauthenticated or forged decision | False safety plan | Token auth on every route; identity from server, not body; append-only audit with `decided_by_id` |
| Malicious or malformed request | Crash, injection, data corruption | Strict validation, 20 KB cap, parameterized key access (no string-built queries from user input), generic 500s |
| AI hallucination (invented action, activity, number, medical claim) | Unsafe or misleading advice | Constrained context, locked schema, feasibility + number-grounding + medical-term checks, engine numbers always win, deterministic fallback |
| Prompt injection via free text (names/notes) | Manipulated AI output | Output is validated against engine data regardless of what the model was told; admin-only data entry; notes are never sent to the model |
| Stale or wrong environmental data | Poor recommendations | Freshness status, confidence cap, warnings, no fabrication when unavailable |
| Replay mistaken for live | Misleading demo | `mode` and label on every analysis, shown in the UI |
| Live provider outage | No data | Last trusted reading (<= 3 h, flagged) else unavailable state |
| Bedrock cost abuse / DoS | Spend, latency | Throttling, AI optional, 20 KB body cap, 30 s timeout |
| Over-claiming science | Credibility | "Modeled exposure index" wording, disclaimer on every analysis, documented assumptions |
| Tampering with history | Loss of accountability | Conditional writes; decisions never edited, only superseded |
