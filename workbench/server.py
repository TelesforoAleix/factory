"""The local dashboard server (ADR-036).

Binds ``127.0.0.1`` only. No application login: the OS user boundary is
sufficient for a single-user local tool, and inventing an auth system for it
would be ceremony with a maintenance cost. **Not for public exposure** — that
would need its own decision (ADR-035 §7).

Two responsibilities and no more:

1. **Parse records and serve JSON.** The browser never parses a record
   (ADR-036 §3). This is why ``parseLooseYaml`` — a hand-rolled YAML subset that
   silently dropped nested structure — is gone from the write path.
2. **Translate HTTP into engine calls.** It implements no write of its own. If
   a write exists here that the CLI cannot do, ADR-036 §1 has eroded.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from workbench import audit, project, records, schema
from workbench.engine import Engine
from workbench.errors import WorkbenchError
from workbench.identity import human

DASHBOARD_DIR = Path(__file__).resolve().parent.parent / "dashboard"


class Handler(BaseHTTPRequestHandler):
    server_version = "FactoryWorkbench/0.1"

    # Injected by serve().
    project_path: Path
    actor_name: str

    # -- plumbing ----------------------------------------------------------

    def _send(self, status: int, payload: dict | list, *, content_type: str = "application/json"):
        body = json.dumps(payload, indent=2, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # The page is same-origin with the API; no cross-origin access is wanted.
        self.send_header("Access-Control-Allow-Origin", "null")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path):
        if not path.is_file():
            self._send(404, {"error": f"not found: {path.name}"})
            return
        kinds = {".html": "text/html", ".css": "text/css", ".js": "text/javascript"}
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", kinds.get(path.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _engine(self) -> Engine:
        proj = project.open_project(self.project_path)
        return Engine(proj, actor=human(self.actor_name, proj.project_id))

    def log_message(self, fmt, *args):  # quieter than the stdlib default
        pass

    # -- routes ------------------------------------------------------------

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        try:
            if path == "/api/records":
                proj = project.open_project(self.project_path)
                everything = records.load_all(proj.ops)
                # Records reach the browser already parsed. This is the whole point.
                self._send(200, {
                    "project_id": proj.project_id,
                    "records": {k: [self._clean(r) for r in v] for k, v in everything.items()},
                })
                return
            if path == "/api/audit":
                proj = project.open_project(self.project_path)
                self._send(200, {"entries": audit.read(proj.ops),
                                 "chain_problems": audit.verify(proj.ops)})
                return
            if path == "/api/validate":
                proj = project.open_project(self.project_path)
                problems = []
                for object_type in schema.SCHEMAS:
                    for record in records.load_collection(proj.ops, object_type):
                        problems += schema.validate(record)
                problems += records.check_links(proj.ops)
                self._send(200, {"problems": problems, "valid": not problems})
                return
            if path in ("/", "/index.html"):
                self._send_file(DASHBOARD_DIR / "index.html")
                return
            if path.lstrip("/") in ("dashboard.js", "styles.css", "workbench.js"):
                self._send_file(DASHBOARD_DIR / path.lstrip("/"))
                return
            self._send(404, {"error": f"no route {path}"})
        except WorkbenchError as error:
            self._send(400, {"error": str(error), "refused": True})

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError as exc:
            self._send(400, {"error": f"body is not JSON: {exc}"})
            return

        try:
            engine = self._engine()
            # Every branch below is a call on the engine. No write lives here.
            if path == "/api/create":
                record = engine.create(payload["type"], payload.get("fields", {}))
                self._send(200, {"ok": True, "record": self._clean(record)})
            elif path == "/api/update":
                record = engine.update(payload["id"], payload.get("changes", {}))
                self._send(200, {"ok": True, "record": self._clean(record)})
            elif path == "/api/status":
                record = engine.set_status(payload["id"], payload["status"])
                self._send(200, {"ok": True, "record": self._clean(record)})
            elif path == "/api/approve":
                approval = engine.grant_approval(payload["id"])
                self._send(200, {"ok": True, "record": self._clean(approval)})
            elif path == "/api/roster-add":
                data = engine.add_to_roster(payload["agent"], scope=payload.get("scope", "team"))
                self._send(200, {"ok": True, "roster": data.get("roster", [])})
            else:
                self._send(404, {"error": f"no route {path}"})
        except WorkbenchError as error:
            # A refusal is a 409, not a 500: it is a correct outcome, not a fault.
            self._send(409, {"error": str(error), "refused": True})
        except KeyError as error:
            self._send(400, {"error": f"missing field {error}"})

    @staticmethod
    def _clean(record: dict) -> dict:
        return {k: v for k, v in record.items() if not k.startswith("_")}


def serve(project_path: Path, *, host: str = "127.0.0.1", port: int = 8765,
          actor: str = "owner") -> None:
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise WorkbenchError(
            f"refusing to bind {host!r}: Workbench is loopback-only (ADR-035 §7, ADR-036 §5). "
            f"Public exposure needs its own decision."
        )
    proj = project.open_project(project_path)
    Handler.project_path = project_path
    Handler.actor_name = actor

    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"Factory Workbench — project {proj.project_id}")
    print(f"  http://{host}:{port}/   (loopback only; ctrl-c to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.server_close()
