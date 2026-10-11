# BreatheOps

*Don't just measure the air. Change what happens because of it.*

BreatheOps turns air-quality data and a school's real timetable into explainable, feasible, human-approved schedule actions.

## Features

- Deterministic exposure analysis and activity planning
- Feasibility checks and safety guardrails
- Replay-based air-quality scenarios for reliable demonstrations
- Optional AI planner abstraction with a deterministic fallback
- Decision history and audit attribution
- Local API server that runs without AWS credentials
- AWS Serverless Application Model (SAM) infrastructure template

## Run locally

Use Python 3.12 for the tested environment.

Install the test dependency:

```bash
python -m pip install pytest
```

Run the demonstration:

```bash
python backend/demo.py
```

The demonstration uses a replay scenario with AQI 238.

Run the test suite:

```bash
python -m pytest -q backend/tests
```

The project has passed 86 tests in the current development environment.

Start the local API server:

```bash
python backend/local_server.py
```

The local API is available at `http://localhost:8787`. Local replay mode does not require AWS credentials.

## Project structure

| Path | Purpose |
|---|---|
| `backend/src/breatheops/` | Exposure analysis, candidate actions, planning, trust guardrails and analysis logic |
| `backend/src/breatheops/providers/` | Environment provider abstractions, including replay and live-provider scaffolding |
| `backend/src/breatheops/ai.py` | Optional Bedrock planner abstraction and deterministic planner |
| `backend/src/breatheops/services.py` | Analysis, decision, history, daily-plan and campus services |
| `backend/src/breatheops/api.py` | API routing, request validation and response handling |
| `backend/src/breatheops/handler.py` | Lambda entry point |
| `backend/src/breatheops/repository.py` | Memory and DynamoDB repository implementations |
| `backend/src/breatheops/config.py` | Configuration and environment validation |
| `backend/src/breatheops/auth.py` | Authentication service |
| `backend/src/breatheops/observability.py` | Structured logging and observability |
| `infra/template.yaml` | SAM infrastructure for HTTP API, Lambda, DynamoDB and CloudWatch |
| `frontend/` | Frontend prototype; verify API integration before describing it as production-connected |
| `amplify-site/` | Static frontend deployment files |
| `docs/` | Architecture, exposure model, AI, API, security, threat model, frontend and pitch documentation |

## Configuration and security

- Never commit real credentials, API keys or administrator tokens.
- Use `.env.example` as a reference when configuring local development.
- Keep `.env` out of version control.
- In AWS, use the Lambda execution role for AWS service access.
- Store production secrets in an appropriate secret-management service.
- Configure production authentication and an explicit HTTPS frontend origin before public deployment.
- Review `docs/SECURITY.md` and `docs/THREAT_MODEL.md` before deployment.

The current deployment template grants DynamoDB access through `DynamoDBCrudPolicy`. **Bedrock invocation permission is not currently included in the template**, so do not assume that the deployed Lambda can invoke a Bedrock model.

## Reproducible demo

`docs/canonical_demo.json` is the project's canonical demonstration dataset. `backend/freeze_demo.py` is used to freeze the demonstration data and help prevent unintended drift in documented results.

## AWS deployment checklist

Deployment is not complete until the following steps have been verified:

1. Review and validate `infra/template.yaml`.
2. Configure a dedicated, least-privilege AWS deployment identity.
3. Build and validate the SAM application.
4. Configure production settings, including `AppEnv=production`, `AuthMode=token`, a strong administrator token and an explicit HTTPS `AllowedOrigin`.
5. Deploy the backend to the selected AWS region.
6. Configure the live environment provider only after its source parser and API settings are implemented and tested.
7. Seed DynamoDB if required by the application workflow.
8. Connect the frontend to the deployed API and verify authentication, CORS, error handling and end-to-end functionality.
9. Test the deployed application before presenting it as production-ready.

Bedrock integration requires a separate permissions and configuration review before enabling it.

## Project status

BreatheOps has a tested local backend and an AWS SAM infrastructure template. Public repository publication does not itself mean that the AWS backend is deployed or that the complete frontend-to-backend integration is live.

## License

Add a license file if you intend to grant others explicit permission to reuse, modify or distribute this project.
