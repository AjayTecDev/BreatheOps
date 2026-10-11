# Security

| Area | What exists now | What is deliberately not built |
|---|---|---|
| Authentication | `AuthService` interface. `demo` (local only) and `token` (single shared administrator bearer token, constant-time compare). Production config refuses `demo`. | Cognito/OIDC, per-user accounts, roles |
| Attribution | Decisions are attributed to the server-derived principal. `X-Admin-Name` is a display label only (control chars stripped, 60 chars). The request body can never set identity. | |
| Input validation | Strict at the edge (ids, enums, HH:MM, ranges, body size 20 KB, object bodies only) and in the domain (`Zone`/`Activity` reject negative or impossible values). | |
| Secrets | None in the repo (a test scans for key-shaped strings). `.env` is git-ignored. Settings never print secrets; error messages name variables, not values. AWS credentials come from the Lambda role. | |
| CORS | `ALLOWED_ORIGIN`; production requires an https origin. | |
| IAM | `DynamoDBCrudPolicy` on one table; `bedrock:InvokeModel` scoped by `BedrockModelArn` (replace `*` before submission). | |
| Abuse / cost | HTTP API throttling (burst 20, 10 rps) also caps Bedrock spend. | WAF |
| Logging | Structured JSON, correlation id per request, secret-looking fields redacted. | |
| Data integrity | Analyses, snapshots, decisions are write-once (conditional puts). | |

Before submission: set `APP_ENV=production`, `AUTH_MODE=token`, a long `ADMIN_TOKEN` from SSM/Secrets Manager, the https `ALLOWED_ORIGIN`, and the Bedrock model ARN.
