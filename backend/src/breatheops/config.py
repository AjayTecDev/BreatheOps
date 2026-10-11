"""The ONLY place that reads environment variables. Replay/local mode needs no credentials."""
from __future__ import annotations
import os
from dataclasses import dataclass, field


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    app_env: str = "local"                    # local | production
    environment_provider: str = "replay"      # replay | live
    aws_region: str = ""
    table: str = ""                           # empty = in-memory repository
    bedrock_model_id: str = ""                # empty = AI off, deterministic planner only
    environment_api_url: str = ""
    environment_api_key: str = field(default="", repr=False)
    auth_mode: str = "demo"                   # demo | token
    admin_token: str = field(default="", repr=False)
    allowed_origin: str = "*"
    default_school_id: str = "demo-school"

    @property
    def ai_enabled(self) -> bool:
        return bool(self.bedrock_model_id)

    @classmethod
    def from_env(cls, env=None) -> "Settings":
        e = os.environ if env is None else env
        g = lambda k, d="": (e.get(k) or d).strip()
        return cls(g("APP_ENV", "local").lower(), g("ENVIRONMENT_PROVIDER", "replay").lower(), g("AWS_REGION"),
                   g("TABLE"), g("BEDROCK_MODEL_ID"), g("ENVIRONMENT_API_URL"), g("ENVIRONMENT_API_KEY"),
                   g("AUTH_MODE", "demo").lower(), g("ADMIN_TOKEN"), g("ALLOWED_ORIGIN", "*"))

    def validate(self) -> list[str]:
        """Problems, naming variables only (never values)."""
        p = []
        if self.app_env not in ("local", "production"): p.append("APP_ENV must be local or production")
        if self.environment_provider not in ("replay", "live"): p.append("ENVIRONMENT_PROVIDER must be replay or live")
        if self.auth_mode not in ("demo", "token"): p.append("AUTH_MODE must be demo or token")
        if self.environment_provider == "live":
            if not self.environment_api_url: p.append("ENVIRONMENT_API_URL is required when ENVIRONMENT_PROVIDER=live")
            if not self.environment_api_key: p.append("ENVIRONMENT_API_KEY is required when ENVIRONMENT_PROVIDER=live")
        if self.auth_mode == "token" and len(self.admin_token) < 16:
            p.append("ADMIN_TOKEN (min 16 chars) is required when AUTH_MODE=token")
        if self.app_env == "production":
            if not self.table: p.append("TABLE is required in production")
            if self.auth_mode != "token": p.append("AUTH_MODE=token is required in production")
            if not self.allowed_origin.startswith("https://"): p.append("ALLOWED_ORIGIN must be an https:// origin in production")
        return p

    @classmethod
    def load(cls, env=None) -> "Settings":
        s = cls.from_env(env)
        problems = s.validate()
        if problems:
            raise ConfigError("Invalid configuration: " + "; ".join(problems))
        return s
