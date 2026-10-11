import json, sys
from datetime import datetime
import os; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from breatheops.analyze import analyze
from breatheops import seed

now = datetime(2026, 10, 10, 8, 40)
r = analyze(seed.ACTIVITIES, seed.ZONES, seed.demo_snapshot(now), now, *seed.DAY)
e = r["environment"]
print(f"AQI {e['aqi']:.0f} ({e['category']}) | {e['status']} {e['age_minutes']}m | confidence {e['confidence']}\n")
for b, p in zip(r["risk_board"], r["plan"]):
    print(f"{b['time']} {b['name']:<14}{b['setting']:<8}{b['risk']:<7}-> {p['action']:<13}{p['detail']}")
i = r["impact"]
print(f"\nModeled exposure index: {i['baseline_index']} -> {i['proposed_index']}  ({i['label']})")
if "--json" in sys.argv: print(json.dumps(r, indent=2))
