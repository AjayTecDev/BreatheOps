"""Action Candidate Engine: only physically feasible actions are ever offered."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Sequence
from .models import Action, Activity, Zone, fmt
from .exposure import ModelParams, DEFAULT, dose


@dataclass(frozen=True)
class Candidate:
    activity_id: str
    action: Action
    zone_id: str
    start: int
    duration: int
    dose: float
    delta: float   # modeled reduction vs current (>= 0 is better)
    note: str


def _zones(zs: Sequence[Zone]) -> dict:
    return {z.zone_id: z for z in zs}


def _load(schedule, zone_id, start, end, exclude_id) -> int:
    return sum(a.occupancy for a in schedule
               if a.activity_id != exclude_id and a.zone_id == zone_id
               and a.start < end and start < a.end)


def _fits(z: Zone, a: Activity, schedule, start, end) -> bool:
    return z.capacity >= a.occupancy + _load(schedule, z.zone_id, start, end, a.activity_id)


def generate(a: Activity, schedule: Sequence[Activity], zones: Sequence[Zone],
             aqi_at: Callable[[int], float], day_start: int, day_end: int,
             p: ModelParams = DEFAULT) -> list[Candidate]:
    zm = _zones(zones)
    cur_zone = zm[a.zone_id]
    base = dose(aqi_at(a.start), cur_zone.indoor, a.intensity, a.duration, p)
    out = [Candidate(a.activity_id, Action.KEEP, a.zone_id, a.start, a.duration,
                     base, 0.0, "No change")]
    if cur_zone.indoor:
        return out  # indoor activities: nothing to improve

    # MOVE_INDOORS: zone must be indoor, support this activity kind, have capacity
    options = [z for z in zones if z.indoor and a.kind in z.supports
               and _fits(z, a, schedule, a.start, a.end)]
    if options:
        best = max(options, key=lambda z: z.capacity - a.occupancy
                   - _load(schedule, z.zone_id, a.start, a.end, a.activity_id))
        d = dose(aqi_at(a.start), True, a.intensity, a.duration, p)
        out.append(Candidate(a.activity_id, Action.MOVE_INDOORS, best.zone_id, a.start,
                             a.duration, d, base - d, f"Move to {best.name}"))

    # SHORTEN: halve long outdoor sessions (floor 15 min)
    if a.duration >= 30:
        nd = max(15, int(round(a.duration / 2 / 5.0)) * 5)
        d = dose(aqi_at(a.start), False, a.intensity, nd, p)
        out.append(Candidate(a.activity_id, Action.SHORTEN, a.zone_id, a.start, nd,
                             d, base - d, f"Shorten to {nd} min"))

    # RESCHEDULE: only when a forecast shows a genuinely lower-exposure slot (>=10%)
    best_slot = None
    for s in range(day_start, day_end - a.duration + 1, 15):
        if s == a.start or not _fits(cur_zone, a, schedule, s, s + a.duration):
            continue
        d = dose(aqi_at(s), False, a.intensity, a.duration, p)
        if d <= 0.9 * base and (best_slot is None or (d, abs(s - a.start)) < best_slot[:2]):
            best_slot = (d, abs(s - a.start), s)
    if best_slot:
        d, _, s = best_slot
        out.append(Candidate(a.activity_id, Action.RESCHEDULE, a.zone_id, s, a.duration,
                             d, base - d, f"Reschedule to {fmt(s)}"))

    out.append(Candidate(a.activity_id, Action.MONITOR, a.zone_id, a.start, a.duration,
                         base, 0.0, "Keep, re-check conditions before start"))
    return out


def evaluate_custom(a: Activity, schedule: Sequence[Activity], zones: Sequence[Zone],
                    aqi_at: Callable[[int], float], day_start: int, day_end: int,
                    zone_id: str | None = None, start: int | None = None,
                    duration: int | None = None, p: ModelParams = DEFAULT) -> Candidate:
    """Validate an admin's MODIFY (custom zone/start/duration). Raises ValueError if infeasible."""
    zm = _zones(zones)
    zid = zone_id or a.zone_id
    s = a.start if start is None else start
    d = a.duration if duration is None else duration
    if zid not in zm:
        raise ValueError(f"unknown zone {zid!r}")
    z = zm[zid]
    if a.kind not in z.supports:
        raise ValueError(f"{z.name} cannot host {a.kind}")
    if d <= 0 or d > a.duration:
        raise ValueError("duration must be between 1 and the original duration")
    if s < day_start or s + d > day_end:
        raise ValueError("outside operating hours")
    if not _fits(z, a, schedule, s, s + d):
        raise ValueError(f"{z.name} lacks capacity at that time")
    base = dose(aqi_at(a.start), zm[a.zone_id].indoor, a.intensity, a.duration, p)
    new = dose(aqi_at(s), z.indoor, a.intensity, d, p)
    action = (Action.MOVE_INDOORS if zid != a.zone_id and z.indoor else
              Action.RESCHEDULE if s != a.start else
              Action.SHORTEN if d != a.duration else Action.KEEP)
    return Candidate(a.activity_id, action, zid, s, d, new, base - new,
                     f"Custom: {z.name}, {fmt(s)}, {d} min")
