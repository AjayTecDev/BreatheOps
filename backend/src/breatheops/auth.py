"""AuthService: the plug-in point for real authentication. Decisions are attributed to the
server-derived Principal, never to a name the client puts in the request body."""
from __future__ import annotations
import hmac
from dataclasses import dataclass
from typing import Mapping, Protocol
from .errors import ServiceError


@dataclass(frozen=True)
class Principal:
    id: str
    name: str     # display name for the audit trail


def _label(headers: Mapping[str, str]) -> str | None:
    v = "".join(c for c in headers.get("x-admin-name", "") if c.isprintable()).strip()[:60]
    return v or None


class AuthService(Protocol):
    def authenticate(self, headers: Mapping[str, str]) -> Principal: ...


class DemoAuthService:
    """Local development only (AUTH_MODE=demo). Refused in production by config validation."""
    def authenticate(self, headers):
        return Principal("DEMO_ADMIN", _label(headers) or "DEMO_ADMIN")


class TokenAuthService:
    """Single shared administrator token (Authorization: Bearer ...). Swap for Cognito/OIDC later."""
    def __init__(self, token: str):
        self._token = token.encode()

    def authenticate(self, headers):
        scheme, _, tok = headers.get("authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not tok or not hmac.compare_digest(tok.strip().encode(), self._token):
            raise ServiceError("UNAUTHORIZED", "Valid administrator credentials are required.", 401)
        return Principal("admin", _label(headers) or "School administrator")


def build_auth(settings) -> AuthService:
    return TokenAuthService(settings.admin_token) if settings.auth_mode == "token" else DemoAuthService()
