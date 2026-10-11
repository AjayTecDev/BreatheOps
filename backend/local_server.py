"""Local dev server (no AWS): in-memory DynamoDB twin seeded with the demo school.
  python3 backend/local_server.py   ->  http://localhost:8787   (frontend can point here)"""
import json, os, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlparse
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from breatheops.api import App
from breatheops.config import Settings
from breatheops.repository import MemoryRepository
from breatheops import seed

repo = MemoryRepository(); seed.seed_repository(repo)
app = App(Settings.load(), repo, sink=lambda e: print(json.dumps(e)))


class H(BaseHTTPRequestHandler):
    def _go(self, method):
        u = urlparse(self.path)
        n = min(int(self.headers.get("Content-Length") or 0), 20_000)
        try: body, bad = json.loads(self.rfile.read(n) or b"null"), False
        except ValueError: body, bad = None, True
        status, payload = ((400, {"success": False, "error": {"code": "INVALID_REQUEST", "message": "invalid JSON"}})
                           if bad else app.handle(method, u.path, dict(parse_qsl(u.query)), body, dict(self.headers)))
        data = json.dumps(payload).encode()
        self.send_response(status)
        for k, v in {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*",
                     "Access-Control-Allow-Headers": "content-type,authorization,x-admin-name", "Content-Length": str(len(data))}.items():
            self.send_header(k, v)
        self.end_headers(); self.wfile.write(data)
    def do_GET(self): self._go("GET")
    def do_POST(self): self._go("POST")
    def do_OPTIONS(self):
        self.send_response(204)
        for k, v in {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "content-type,authorization,x-admin-name",
                     "Access-Control-Allow-Methods": "GET,POST,OPTIONS"}.items(): self.send_header(k, v)
        self.end_headers()

if __name__ == "__main__":
    print("BreatheOps local API on http://localhost:8787"); ThreadingHTTPServer(("127.0.0.1", 8787), H).serve_forever()
