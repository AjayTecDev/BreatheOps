"""AI layer. AIPlanner = BedrockPlanner | DeterministicPlanner. The model sees ONLY the constrained
context (environment + risk + each activity's feasible actions); output must pass planner.validate_ai_output."""
from __future__ import annotations
import json
from typing import Optional, Protocol
from .exposure import cpcb_category

SCHEMA_EXAMPLE = {"recommendations": [{
    "activity_id": "a1", "action": "MOVE_INDOORS",
    "reason": "Outdoor assembly at AQI 238 is the largest avoidable exposure.",
    "evidence": ["AQI 238 (Poor)", "Main Building can host 30 min"],
    "confidence": "High", "modeled_impact": {"before": 13.92, "after": 4.18}}]}

SYSTEM = (
    "You are the planning assistant inside BreatheOps, a school air-quality decision-support tool. "
    "For EACH activity choose exactly one action from its feasible_actions. Never invent actions, activities, "
    "locations, times or numbers: every number you write must appear in the provided data. Make no medical or "
    "health claims. Prefer no change when risk is LOW. reason: at most two sentences. evidence: 1-4 short facts "
    "from the data. confidence: High, Medium or Low, never above data_confidence. modeled_impact must copy "
    "modeled_dose (before) and the chosen action's modeled_dose_after (after). Respond with JSON only, no "
    "markdown, in exactly this shape: " + json.dumps(SCHEMA_EXAMPLE)
)


def build_context(snapshot, trust, activities, zm, risk, cands) -> dict:
    from .models import fmt
    return {
        "environment": {"aqi": snapshot.aqi, "category": cpcb_category(snapshot.aqi),
                        "data_status": trust["status"], "data_confidence": trust["confidence"]},
        "activities": [{
            "activity_id": a.activity_id, "name": a.name, "time": fmt(a.start),
            "duration_min": a.duration,
            "setting": "indoor" if zm[a.zone_id].indoor else "outdoor",
            "risk": risk[a.activity_id][1], "modeled_dose": round(risk[a.activity_id][0], 2),
            "feasible_actions": [{"action": c.action.value, "detail": c.note,
                                  "modeled_dose_after": round(c.dose, 2)} for c in cands[a.activity_id]],
        } for a in activities],
    }


def parse_json(text: str):
    t = text.strip().replace("```json", "").replace("```", "")
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j < i:
        return None
    try:
        return json.loads(t[i:j + 1])
    except json.JSONDecodeError:
        return None


class AIPlanner(Protocol):
    def rank(self, context: dict) -> Optional[dict]: ...


class DeterministicPlanner:
    """No AI: rank() returns None, so analyze() uses the rule-based plan."""
    def rank(self, context: dict) -> Optional[dict]:
        return None


class BedrockPlanner:
    """Amazon Bedrock Converse. Credentials come from the runtime IAM role, never from code."""
    def __init__(self, client=None, model_id: str | None = None, max_tokens: int = 1200):
        self.client, self.model_id, self.max_tokens = client, model_id, max_tokens

    def rank(self, context: dict) -> Optional[dict]:
        mid = self.model_id
        if not mid:
            raise RuntimeError("BEDROCK_MODEL_ID not set")
        c = self.client
        if c is None:
            import boto3  # present in the Lambda runtime
            c = self.client = boto3.client("bedrock-runtime")
        resp = c.converse(modelId=mid, system=[{"text": SYSTEM}],
                          messages=[{"role": "user", "content": [{"text": json.dumps(context)}]}],
                          inferenceConfig={"maxTokens": self.max_tokens, "temperature": 0})
        return parse_json(resp["output"]["message"]["content"][0]["text"])


def make_ranker(client=None, model_id: str | None = None):
    """Back-compat: ranker callable for analyze(ai_ranker=...)."""
    return BedrockPlanner(client, model_id).rank
