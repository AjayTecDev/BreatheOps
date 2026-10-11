"""Regenerate docs/canonical_demo.json. Run ONLY when you deliberately change the model,
then update docs/PITCH.md to match (tests enforce both)."""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, "src"))
from datetime import datetime
from breatheops.analyze import analyze
from breatheops import seed

NOW = datetime(2026, 10, 10, 8, 40)
r = analyze(seed.ACTIVITIES, seed.ZONES, seed.demo_snapshot(NOW), NOW, *seed.DAY)
path = os.path.join(HERE, "..", "docs", "canonical_demo.json")
json.dump(r, open(path, "w"), indent=2, ensure_ascii=False)
print("frozen:", r["impact"]["label"])
