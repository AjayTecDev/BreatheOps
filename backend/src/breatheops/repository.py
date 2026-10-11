"""One Repository contract, two backends: MemoryRepository (local/tests) and DynamoRepository (AWS).
Single-table design:
  SCHOOL#<id> | META | ZONE#<id> | ACTIVITY#<id> | SNAPSHOT#<snapshotId> | ANALYSIS#<analysisId>
              | DECISION#<analysisId>#<decisionId>      (append-only: written once, never updated)"""
from __future__ import annotations
import json
from dataclasses import fields
from datetime import datetime
from decimal import Decimal
from typing import Optional, Protocol
from .models import Activity, Snapshot, Zone


class DuplicateError(Exception):
    """Raised when an immutable record is written twice."""


def to_ddb(v):  # DynamoDB rejects float
    if isinstance(v, float): return Decimal(str(v))
    if isinstance(v, dict): return {k: to_ddb(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)): return [to_ddb(x) for x in v]
    return v


def from_ddb(v):
    if isinstance(v, Decimal): return int(v) if v == v.to_integral_value() else float(v)
    if isinstance(v, dict): return {k: from_ddb(x) for k, x in v.items()}
    if isinstance(v, list): return [from_ddb(x) for x in v]
    return v


def _strip(item: dict) -> dict:
    return {k: x for k, x in item.items() if k not in ("pk", "sk")}


class MemoryStore:
    def __init__(self): self.items: dict = {}
    def put(self, pk, sk, item, if_absent=False):
        if if_absent and (pk, sk) in self.items: raise DuplicateError(sk)
        self.items[(pk, sk)] = json.loads(json.dumps(item))   # must be JSON-safe, like a real table
    def get(self, pk, sk):
        v = self.items.get((pk, sk)); return json.loads(json.dumps(v)) if v is not None else None
    def query(self, pk, prefix, newest_first=False, limit=None):
        rows = sorted(((sk, v) for (p, sk), v in self.items.items() if p == pk and sk.startswith(prefix)),
                      key=lambda r: r[0], reverse=newest_first)
        return [json.loads(json.dumps(v)) for _, v in rows[:limit]]


class DynamoStore:
    """`table` is a boto3 Table resource. Credentials come from the IAM role/environment, never from code."""
    def __init__(self, table): self.t = table
    def put(self, pk, sk, item, if_absent=False):
        kw = {"Item": to_ddb({**item, "pk": pk, "sk": sk})}
        if if_absent: kw["ConditionExpression"] = "attribute_not_exists(pk)"
        try:
            self.t.put_item(**kw)
        except Exception as e:
            if getattr(e, "response", {}).get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                raise DuplicateError(sk) from None
            raise
    def get(self, pk, sk):
        it = self.t.get_item(Key={"pk": pk, "sk": sk}).get("Item")
        return _strip(from_ddb(it)) if it else None
    def query(self, pk, prefix, newest_first=False, limit=None):
        kw = {"KeyConditionExpression": "pk = :pk AND begins_with(sk, :p)",
              "ExpressionAttributeValues": {":pk": pk, ":p": prefix}, "ScanIndexForward": not newest_first}
        if limit: kw["Limit"] = limit
        out = []
        while True:
            r = self.t.query(**kw)
            out += [_strip(from_ddb(i)) for i in r.get("Items", [])]
            if not r.get("LastEvaluatedKey") or (limit and len(out) >= limit): break
            kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]
        return out[:limit] if limit else out


def zone_to_item(z: Zone) -> dict:
    return {"zone_id": z.zone_id, "name": z.name, "indoor": z.indoor, "capacity": z.capacity, "supports": sorted(z.supports)}

def zone_from_item(i: dict) -> Zone:
    return Zone(i["zone_id"], i["name"], bool(i["indoor"]), int(i["capacity"]), frozenset(i["supports"]))

def activity_to_item(a: Activity) -> dict:
    return {"activity_id": a.activity_id, "name": a.name, "kind": a.kind, "start": a.start, "duration": a.duration,
            "zone_id": a.zone_id, "occupancy": a.occupancy, "intensity": a.intensity}

def activity_from_item(i: dict) -> Activity:
    return Activity(i["activity_id"], i["name"], i["kind"], int(i["start"]), int(i["duration"]),
                    i["zone_id"], int(i["occupancy"]), i["intensity"])

def snapshot_to_item(s: Snapshot) -> dict:
    d = {f.name: getattr(s, f.name) for f in fields(s)}
    d["observed_at"] = s.observed_at.isoformat()
    d["retrieved_at"] = s.retrieved_at.isoformat() if s.retrieved_at else None
    return d

def snapshot_from_item(i: dict) -> Snapshot:
    return Snapshot(float(i["aqi"]), i.get("pm25"), i["source"], i["station"], datetime.fromisoformat(i["observed_at"]),
                    i["mode"], datetime.fromisoformat(i["retrieved_at"]) if i.get("retrieved_at") else None,
                    i.get("quality", "OK"), i.get("snapshot_id"))


class RepositoryAPI(Protocol):
    """The contract both repositories fulfil (checked by tests)."""
    def put_school(self, sid, meta): ...
    def get_school(self, sid) -> Optional[dict]: ...
    def put_zones(self, sid, zones): ...
    def list_zones(self, sid) -> list: ...
    def put_activities(self, sid, acts): ...
    def list_activities(self, sid) -> list: ...
    def save_snapshot(self, sid, snap: Snapshot): ...
    def latest_snapshot(self, sid, mode: str) -> Optional[Snapshot]: ...
    def save_analysis(self, sid, analysis): ...
    def get_analysis(self, sid, aid) -> Optional[dict]: ...
    def list_analyses(self, sid, limit=20) -> list: ...
    def save_decision(self, sid, d): ...
    def list_decisions(self, sid, aid) -> list: ...


class Repository:
    def __init__(self, store): self.s = store
    @staticmethod
    def _pk(sid: str) -> str: return f"SCHOOL#{sid}"

    def put_school(self, sid, meta): self.s.put(self._pk(sid), "META", dict(meta))
    def get_school(self, sid): return self.s.get(self._pk(sid), "META")
    def put_zones(self, sid, zones):
        for z in zones: self.s.put(self._pk(sid), f"ZONE#{z.zone_id}", zone_to_item(z))
    def list_zones(self, sid): return [zone_from_item(i) for i in self.s.query(self._pk(sid), "ZONE#")]
    def put_activities(self, sid, acts):
        for a in acts: self.s.put(self._pk(sid), f"ACTIVITY#{a.activity_id}", activity_to_item(a))
    def list_activities(self, sid):
        return sorted((activity_from_item(i) for i in self.s.query(self._pk(sid), "ACTIVITY#")), key=lambda a: a.start)
    def save_snapshot(self, sid, snap: Snapshot):
        self.s.put(self._pk(sid), f"SNAPSHOT#{snap.snapshot_id}", snapshot_to_item(snap), if_absent=True)
    def latest_snapshot(self, sid, mode):
        for it in self.s.query(self._pk(sid), "SNAPSHOT#", True, 20):
            if it["mode"] == mode and it.get("quality") != "DEGRADED":
                return snapshot_from_item(it)
        return None
    def save_analysis(self, sid, analysis): self.s.put(self._pk(sid), f"ANALYSIS#{analysis['analysis_id']}", analysis, if_absent=True)
    def get_analysis(self, sid, aid): return self.s.get(self._pk(sid), f"ANALYSIS#{aid}")
    def list_analyses(self, sid, limit=20): return self.s.query(self._pk(sid), "ANALYSIS#", True, limit)
    def save_decision(self, sid, d):
        self.s.put(self._pk(sid), f"DECISION#{d['analysis_id']}#{d['decision_id']}", d, if_absent=True)
    def list_decisions(self, sid, aid):
        return sorted(self.s.query(self._pk(sid), f"DECISION#{aid}#"), key=lambda d: (d["decided_at"], d.get("seq", 0)))


class MemoryRepository(Repository):
    def __init__(self): super().__init__(MemoryStore())


class DynamoRepository(Repository):
    def __init__(self, table): super().__init__(DynamoStore(table))
