# Where every real key and setting goes

Nothing secret is ever put in the zip, the HTML page, or Git.

| What | Where to put it | Notes |
|---|---|---|
| **API Gateway URL** (not a secret) | `frontend/index.template.html`, block `CONFIG.API_BASE`, then run `python frontend/build.py` | Shown after `sam deploy` as `ApiUrl`. Empty = demo mode. |
| **Access code for staff** | `CONFIG.AUTH = "token"` in the same block. Server side: SAM parameters `AuthMode=token`, `AdminToken=<code>` | Create one: `python -c "import secrets;print(secrets.token_urlsafe(32))"`. Share it only with administrators. |
| **AWS credentials** | Never in code. On AWS the Lambda role provides them. On your laptop use `aws configure sso` | Only needed for `sam deploy` and `backend/scripts/seed_table.py`. |
| **Bedrock model** | SAM parameters `BedrockModelId` and `BedrockModelArn` (`sam deploy --guided`) | Enable the model in your region first. Empty model ID = rule-based planning only. |
| **Environment data API URL / key** | SAM parameters `EnvironmentProvider=live`, `EnvironmentApiUrl`, `EnvironmentApiKey` | Then write the source's response parser in `backend/src/breatheops/providers.py` and pass it as `parser=` where `LiveProvider` is created in `api.py`. Header name: `auth_header=`. |
| **Frontend web address** | SAM parameter `AllowedOrigin` (must be `https://...` in production) | Also `AppEnv=production`. |
| **Local testing settings** | In CMD: `set ENVIRONMENT_PROVIDER=replay` then `python backend\local_server.py` | `.env` is not loaded automatically. |

## Honest production gaps (not built yet)
1. **Live data adapter:** needs the chosen source's response format.
2. **Secrets at runtime:** the template passes `EnvironmentApiKey` and `AdminToken` as Lambda environment variables (hidden in CloudFormation, visible in the Lambda console). For stricter security read them from SSM Parameter Store or Secrets Manager at startup.
3. **Real user accounts:** the access code is one shared code. Cognito or similar would give each administrator their own login.
4. **Hosting and HTTPS:** serve the page from S3 + CloudFront (or any HTTPS host) with a Content-Security-Policy header.
5. **Alarm notifications:** the CloudWatch alarm exists but has no email subscription.
6. **Deploy and test end to end** with real services.
