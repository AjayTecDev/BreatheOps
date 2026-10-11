"""AWS Lambda entrypoint (API Gateway HTTP API v2). Thin: parse event -> App.handle -> respond.
No business logic, no credentials: DynamoDB/Bedrock use the function's IAM role."""
import base64, json, uuid
from .api import App
from .ai import BedrockPlanner, DeterministicPlanner
from .config import Settings
from .repository import DynamoRepository, MemoryRepository
from . import seed

MAX_BODY = 20_000
_app = None


def _sink(entry: dict) -> None:   # structured JSON -> CloudWatch Logs
    print(json.dumps(entry, default=str))


def get_app() -> App:
    global _app
    if _app is None:
        cfg = Settings.load()      # raises a clear ConfigError at cold start if misconfigured
        if cfg.table:
            import boto3
            repo = DynamoRepository(boto3.resource("dynamodb", region_name=cfg.aws_region or None).Table(cfg.table))
        else:                      # local/demo only (production config requires TABLE)
            repo = MemoryRepository(); seed.seed_repository(repo)
        planner = BedrockPlanner(model_id=cfg.bedrock_model_id) if cfg.ai_enabled else DeterministicPlanner()
        _app = App(cfg, repo, planner, sink=_sink)
    return _app


def _resp(status: int, payload: dict, rid: str) -> dict:
    return {"statusCode": status, "headers": {"Content-Type": "application/json", "X-Request-Id": rid},
            "body": json.dumps(payload)}


def lambda_handler(event, context=None):
    http = (event.get("requestContext") or {}).get("http") or {}
    rid = (event.get("requestContext") or {}).get("requestId") or uuid.uuid4().hex[:12]
    raw = event.get("body") or ""
    if event.get("isBase64Encoded") and raw:
        raw = base64.b64decode(raw).decode("utf-8", "replace")
    if len(raw) > MAX_BODY:
        return _resp(413, {"success": False, "error": {"code": "PAYLOAD_TOO_LARGE", "message": "request too large"}, "request_id": rid}, rid)
    try:
        body = json.loads(raw) if raw else None
    except ValueError:
        return _resp(400, {"success": False, "error": {"code": "INVALID_REQUEST", "message": "invalid JSON"}, "request_id": rid}, rid)
    status, env = get_app().handle(http.get("method", "GET"), event.get("rawPath", "/"),
                                   event.get("queryStringParameters") or {}, body, event.get("headers") or {}, rid)
    return _resp(status, env, rid)
