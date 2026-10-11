"""Demo school: Green Valley Public School, Bidar. Used for the REPLAY scenario (AQI 238)."""
from datetime import datetime, timedelta
from .models import Activity, Snapshot, Zone, hm

SCHOOL_ID = "demo-school"
SCHOOL = {"name": "Green Valley Public School", "location": "Bidar", "student_count": 1200,
          "day_start": "08:30", "day_end": "16:00"}
ZONES = [
    Zone("main", "Main Building", True, 1500, frozenset({"class", "assembly"})),
    Zone("assembly", "Assembly Ground", False, 1500, frozenset({"assembly"})),
    Zone("sports", "Sports Ground", False, 500, frozenset({"sports"})),
    Zone("cafe", "Cafeteria", True, 600, frozenset({"lunch"})),
    Zone("bus", "Bus Area", False, 300, frozenset({"transit"})),
]
ACTIVITIES = [
    Activity("a1", "Assembly", "assembly", hm("09:00"), 30, "assembly", 1200, "sedentary"),
    Activity("a2", "Mathematics", "class", hm("10:30"), 45, "main", 40, "sedentary"),
    Activity("a3", "Sports", "sports", hm("12:00"), 60, "sports", 200, "vigorous"),
    Activity("a4", "Lunch", "lunch", hm("13:00"), 45, "cafe", 300, "sedentary"),
    Activity("a5", "Bus departure", "transit", hm("15:00"), 20, "bus", 300, "light"),
]
DAY = (hm("08:30"), hm("16:00"))


def demo_snapshot(now: datetime, aqi: float = 238, age_min: int = 8) -> Snapshot:
    pm25 = 101.8 if aqi == 238 else None   # PM2.5 consistent with AQI 238 under CPCB breakpoints
    return Snapshot(aqi, pm25, "REPLAY (CPCB-format scenario)", "Bidar (demo)",
                    now - timedelta(minutes=age_min), "REPLAY", now, "OK")


def seed_repository(repo, school_id: str = SCHOOL_ID) -> None:
    repo.put_school(school_id, SCHOOL)
    repo.put_zones(school_id, ZONES)
    repo.put_activities(school_id, ACTIVITIES)
