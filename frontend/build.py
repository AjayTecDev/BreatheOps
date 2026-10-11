"""Assembles the single-file frontend: style.css + index.template.html + canonical demo (offline fallback only).
  python3 frontend/build.py [out.html]"""
import json, os, sys
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
HERE = os.path.join(ROOT, "frontend")
c = json.load(open(os.path.join(ROOT, "docs", "canonical_demo.json"), encoding="utf-8"))
fb = {k: c[k] for k in ("environment", "risk_board", "plan", "impact", "warnings", "disclaimer", "ai")}
fb["school"] = "Green Valley Public School"
html = open(os.path.join(HERE, "index.template.html"), encoding="utf-8").read()
html = html.replace("/*CSS*/", open(os.path.join(HERE, "style.css"), encoding="utf-8").read())
html = html.replace("__FALLBACK__", json.dumps(fb, separators=(",", ":"), ensure_ascii=False))
html = html.replace('API_BASE:"__API_BASE__"', 'API_BASE:' + json.dumps(os.environ.get("BREATHEOPS_API_BASE", "").strip().rstrip("/")))
html = html.replace('AUTH:"__AUTH__"', 'AUTH:' + json.dumps(os.environ.get("BREATHEOPS_AUTH", "demo").strip()))
out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "breatheops-app.html")
open(out, "w", encoding="utf-8").write(html)
print(out, len(html), "bytes")

