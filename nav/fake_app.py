"""Stand-in for the Cosmo web app's robot endpoints, for testing follow.py --app without Vercel.

    python3 nav/fake_app.py [--port 8200] [--token test]
    .venv/bin/python nav/follow.py --app --app-url http://<this machine>:8200      (token file: ROBOT_API_TOKEN=test)

Same rules as the app (docs/robot-link.md): GET /api/robot/inbox returns unacked commands from the last 10 min, oldest
first, again on every poll until acked; POST /api/robot/uplink stores each note once by its id. Bearer token required.
Queue a command with POST /test/command {"type": ..., "body": ...} (id and issuedAt are filled in); GET /test/notes
lists the uplinked notes. Used by nav/tests/test_app_link.py and nav/sim_follow_harness.py --app.
"""
import argparse
import http.server
import json
import threading
import time
import uuid
from datetime import datetime, timezone


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat().replace("+00:00", "Z")


class FakeApp:
    def __init__(self, port=0, token="test", host="127.0.0.1", poll_seconds=3, tls=None):
        self.token, self.poll_seconds = token, poll_seconds
        self.commands = []                       # [{id, type, issuedAt, body, t, acked}]
        self.notes = {}                          # note id -> note, first copy only
        self.order = []
        self.lock = threading.Lock()
        self.offline = False                     # True: every request fails (simulated link loss)
        self.fail_uplinks = 0                    # answer this many uplinks with 503 (retry test)
        self.polls = 0
        app = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, obj):
                b = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def _auth(self):
                if app.offline:
                    self.close_connection = True
                    self.connection.close()
                    return False
                if self.headers.get("Authorization") != f"Bearer {app.token}" and self.path.startswith("/api/"):
                    self._send(401, {"error": "unauthorized"})
                    return False
                return True

            def do_GET(self):
                if not self._auth():
                    return
                if self.path.startswith("/api/robot/inbox"):
                    with app.lock:
                        app.polls += 1
                        now = time.time()
                        cmds = [{k: c[k] for k in ("id", "type", "issuedAt", "body")} for c in app.commands
                                if not c["acked"] and now - c["t"] < 600]
                    return self._send(200, {"now": iso(time.time()), "pollSeconds": app.poll_seconds, "commit": "fake000", "commands": cmds})
                if self.path.startswith("/test/notes"):
                    with app.lock:
                        return self._send(200, [app.notes[i] for i in app.order])
                self._send(404, {"error": "not found"})

            def do_POST(self):
                if not self._auth():
                    return
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"null")
                if self.path.startswith("/api/robot/uplink"):
                    if app.fail_uplinks > 0:
                        app.fail_uplinks -= 1
                        return self._send(503, {"error": "try again"})
                    notes = body if isinstance(body, list) else [body]
                    if any(x.get("kind") not in ("ack", "telemetry") for x in notes):
                        return self._send(400, {"error": "kind must be ack or telemetry"})
                    with app.lock:
                        for x in notes:
                            if x["id"] in app.notes:
                                continue
                            app.notes[x["id"]] = x
                            app.order.append(x["id"])
                            if x["kind"] == "ack":
                                for c in app.commands:
                                    if c["id"] == x["body"].get("id"):
                                        c["acked"] = True
                    return self._send(200, {"stored": len(notes)})
                if self.path.startswith("/test/command"):
                    return self._send(200, app.add(body["type"], body.get("body", {}), body.get("id"), body.get("age", 0)))
                self._send(404, {"error": "not found"})

        self.srv = http.server.ThreadingHTTPServer((host, port), H)
        self.srv.daemon_threads = True
        self.port = self.srv.server_address[1]
        self.url = f"http://{host}:{self.port}"
        if tls:                                  # (certfile, keyfile): serve HTTPS instead
            import ssl
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(*tls)
            self.srv.socket = ctx.wrap_socket(self.srv.socket, server_side=True)
            self.url = f"https://{host}:{self.port}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def add(self, typ, body, cid=None, age=0.0):
        """Queue a command. age: pretend it was issued this many seconds ago (staleness tests)."""
        c = {"id": cid or str(uuid.uuid4()), "type": typ, "issuedAt": iso(time.time() - age), "body": body,
             "t": time.time(), "acked": False}
        with self.lock:
            self.commands.append(c)
        return {"id": c["id"]}

    def acks(self):
        with self.lock:
            return [self.notes[i]["body"] for i in self.order if self.notes[i]["kind"] == "ack"]

    def telemetry(self):
        with self.lock:
            return [self.notes[i]["body"] for i in self.order if self.notes[i]["kind"] == "telemetry"]

    def close(self):
        self.srv.shutdown()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8200)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--token", default="test")
    a = ap.parse_args()
    app = FakeApp(a.port, a.token, a.host)
    print(f"fake app on {app.url}, token {a.token!r}. Queue: curl -X POST {app.url}/test/command "
          f"-d '{{\"type\":\"unlock\",\"body\":{{\"deliveryId\":\"d1\"}}}}'", flush=True)
    seen = 0
    try:
        while True:
            time.sleep(0.5)
            with app.lock:
                new = [app.notes[i] for i in app.order[seen:]]
                seen = len(app.order)
            for x in new:
                print(json.dumps(x), flush=True)
    except KeyboardInterrupt:
        app.close()


if __name__ == "__main__":
    main()
