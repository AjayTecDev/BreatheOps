# Security

| Area | What exists now | What is deliberately not built |
|---|---|---|
| Authentication | `AuthService` interface. `demo` mode is intended for local development; `token` mode uses a shared administrator bearer token with constant-time comparison. Production configuration rejects demo authentication. | Cognito/OIDC, individual user accounts and role-based access control |
| Attribution | Decisions use a server-derived principal. `X-Admin-Name` is a display label, with control characters stripped and length limited. The request body cannot set the identity. | Full individual-user identity management |
| Input validation | Request validation covers identifiers, enums, time formats, ranges, body size and object bodies. Domain models reject invalid values. | — |
| Secrets | `.env` is excluded from version control. Configuration is designed not to log secret values. AWS credentials should come from the Lambda execution role. | Secrets committed to the repository |
| CORS | Configurable allowed origin. Production configuration requires an HTTPS origin. | Wildcard origins for production |
| IAM | The current SAM template grants DynamoDB access through `DynamoDBCrudPolicy` on the configured table. | Bedrock invocation permission is not included in the current template. |
| Abuse and cost | HTTP API throttling limits request rates. | AWS WAF and additional abuse controls |
| Logging | Structured logging and request correlation are implemented; sensitive-looking fields are redacted. | — |
| Data integrity | The repository uses conditional writes for supported write-once records. | — |

## Before deployment

1. Set `AppEnv=production` and `AuthMode=token`.
2. Configure a strong administrator token using an appropriate secret-management service.
3. Set `AllowedOrigin` to the exact HTTPS frontend origin.
4. Verify the Lambda execution role, DynamoDB permissions and API authorization.
5. Test the deployed application and its error handling.

**Bedrock note:** The current infrastructure template does not grant `bedrock:InvokeModel` permission and does not define `BedrockModelArn`. Review and implement narrowly scoped Bedrock permissions separately before enabling Bedrock integration.

This document describes the intended configuration and implementation. Verify each claim against the current source code and deployment template before relying on it in production.
