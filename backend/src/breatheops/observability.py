"""Structured events with a per-request correlation id. Secrets never reach the log."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Callable

SENSITIVE = ("key", "token", "secret", "password", "authorization")


def redact(fields: dict) -> dict:
    out = {}
    for k, v in fields.items():
        if any(s in k.lower() for s in SENSITIVE):
            out[k] = "[redacted]"
        else:
            out[k] = v[:300] if isinstance(v, str) else v
    return out


class RequestLog:
    def __init__(self, sink: Callable[[dict], None], request_id: str):
        self.sink, self.request_id = sink, request_id

    def event(self, name: str, level: str = "INFO", **fields) -> None:
        self.sink({"ts": datetime.now(timezone.utc).isoformat(), "level": level, "event": name,
                   "request_id": self.request_id, **redact(fields)})
