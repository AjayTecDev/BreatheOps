"""BreatheOps Modeled Exposure Index (prototype decision-support score).

dose = severity(AQI) x location_factor x intensity_factor x minutes

NOT a clinical or epidemiological measurement. Used only to compare
scenarios (current vs proposed schedule) under identical assumptions.
All assumptions live in ModelParams and are documented in docs/EXPOSURE_MODEL.md.
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModelParams:
    # (AQI, severity 0..1) anchors; linear interpolation between them.
    # AQI breakpoints follow the CPCB National AQI categories.
    aqi_anchors: tuple = ((0, 0.0), (50, 0.05), (100, 0.15), (200, 0.35),
                          (300, 0.65), (400, 0.85), (500, 1.0))
    indoor_factor: float = 0.3  # assumed indoor/outdoor ratio (ASSUMPTION)
    intensity: dict = field(default_factory=lambda: {
        "sedentary": 1.0, "light": 1.3, "vigorous": 2.0})  # breathing-rate proxy (ASSUMPTION)
    medium_threshold: float = 10.0  # weighted-minutes
    high_threshold: float = 20.0


DEFAULT = ModelParams()


def cpcb_category(aqi: float) -> str:
    for limit, name in ((50, "Good"), (100, "Satisfactory"), (200, "Moderate"),
                        (300, "Poor"), (400, "Very Poor")):
        if aqi <= limit:
            return name
    return "Severe"


def severity(aqi: float, p: ModelParams = DEFAULT) -> float:
    a = max(0.0, min(500.0, float(aqi)))
    pts = p.aqi_anchors
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if a <= x1:
            return y0 + (y1 - y0) * (a - x0) / (x1 - x0)
    return pts[-1][1]


def dose(aqi: float, indoor: bool, intensity: str, minutes: int,
         p: ModelParams = DEFAULT) -> float:
    loc = p.indoor_factor if indoor else 1.0
    return severity(aqi, p) * loc * p.intensity[intensity] * minutes


def risk_band(d: float, p: ModelParams = DEFAULT) -> str:
    if d >= p.high_threshold:
        return "HIGH"
    if d >= p.medium_threshold:
        return "MEDIUM"
    return "LOW"


def index_vs_baseline(before: float, after: float) -> tuple[float, float]:
    """Baseline schedule = 100. Returns (after_index, pct_lower)."""
    if before <= 0:
        return 100.0, 0.0
    idx = 100.0 * after / before
    return round(idx, 1), round(100.0 - idx, 1)
