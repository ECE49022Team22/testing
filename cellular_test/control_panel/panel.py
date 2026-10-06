"""Cellular test control panel. Runs on the LAPTOP (it needs internet for Notehub and SSH to the Pi).

  python3 panel.py                 # then open http://127.0.0.1:8765
  python3 panel.py --env ~/robot.env --ssh-host robot

- Send buttons POST commands to Notehub (commands.qi), exactly like cloud_inject.py.
- The Pi's log (cellular_test/logs/cellular_log.txt) is streamed live over `ssh <host> tail -F`.
- Each sent command is tracked: sent (Notehub HTTP 200) -> received on Pi -> result/ack queued on Pi
  -> ack seen in Notehub (only when you press "Check acks": the Events API rate-limits hard, so it is
  never polled automatically).

Standard library only (works with macOS's python3). Listens on 127.0.0.1 only; the Notehub token stays
in this process and is never sent to the browser.
"""

import argparse
import collections
import json
import os
import re
import shlex
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
API = "https://api.notefile.net"
# Not secrets (see CELLULAR.md section 3); override with PROJECT_UID / DEVICE_UID if the hardware changes.
DEFAULT_PROJECT_UID = "app:45ea1319-9f3d-4738-9ee1-55e662440586"
DEFAULT_DEVICE_UID = "dev:868531063312800"
REMOTE_DIR = "~/testing/cellular_test"
REMOTE_LOG = REMOTE_DIR + "/logs/cellular_log.txt"
ACK_CHECK_MIN_GAP = 5.0  # seconds between Events API calls (1/s got HTTP 429 and blocked sends too)
LINE_RE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\dZ)  (.*)$")


def load_env(path):
    """KEY=VALUE lines -> os.environ (real environment variables win; blank values skipped)."""
    if not path or not os.path.exists(path):
        return False
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                value = value.strip().strip("\"'")
                if value:
                    os.environ.setdefault(key.strip(), value)
    return True


class Panel:
    def __init__(self, ssh_argv):
        self.ssh_argv = ssh_argv  # [] = run the "remote" commands locally (testing on the Pi itself)
        self.lock = threading.Lock()
        self.lines = collections.deque(maxlen=3000)  # (seq, text)
        self.seq = 0
        self.commands = collections.OrderedDict()  # id -> tracking dict
        self.link = {"state": "connecting", "detail": ""}
        self.pi = {}
        self.last_ack_check = 0.0

    # --- running things on the Pi -------------------------------------------------
    def argv(self, remote_cmd):
        return self.ssh_argv + [remote_cmd] if self.ssh_argv else ["sh", "-c", remote_cmd]

    def run(self, remote_cmd, timeout=20):
        try:
            p = subprocess.run(self.argv(remote_cmd), capture_output=True, text=True, timeout=timeout)
            return p.returncode, (p.stdout + p.stderr).strip()
        except subprocess.TimeoutExpired:
            return -1, f"timed out after {timeout}s"

    def add_line(self, text):
        with self.lock:
            self.seq += 1
            self.lines.append((self.seq, text))
        self.track(text)

    def follow_log(self):
        """Stream the Pi's log forever; reconnect when the SSH link drops (unplug, reboot, brownout)."""
        while True:
            self.link = {"state": "connecting", "detail": ""}
            cmd = f"touch {REMOTE_LOG} 2>/dev/null; tail -n 300 -F {REMOTE_LOG}"
            try:
                proc = subprocess.Popen(self.argv(cmd), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            except OSError as e:
                self.link = {"state": "down", "detail": str(e)}
                time.sleep(3)
                continue
            first = True
            for raw in proc.stdout:
                if first:
                    self.link = {"state": "up", "detail": ""}
                    first = False
                self.add_line(raw.rstrip("\n"))
            proc.wait()
            err = proc.stderr.read().strip().splitlines()
            detail = err[-1] if err else f"exit code {proc.returncode}"
            self.link = {"state": "down", "detail": detail}
            self.add_line(f"[panel] log stream from the Pi stopped ({detail}); reconnecting in 3 s")
            time.sleep(3)

    def poll_pi(self):
        cmd = (
            "tmux has-session -t cellular 2>/dev/null && echo logger=running || echo logger=stopped; "
            "vcgencmd get_throttled 2>/dev/null; echo uptime=$(uptime -p); "
            "echo usb0=$(ip -br -4 addr show usb0 2>/dev/null | awk '{print $3}')"
        )
        while True:
            rc, out = self.run(cmd, timeout=15)
            info = {"ok": rc == 0, "checked": time.time()}
            for line in out.splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    info[k.strip()] = v.strip()
            if rc != 0:
                info["error"] = out.splitlines()[-1] if out else f"exit {rc}"
            self.pi = info
            time.sleep(10)

    # --- command tracking ---------------------------------------------------------
    def track(self, text):
        m = LINE_RE.match(text)
        msg = m.group(2).strip() if m else text.strip()
        for prefix, field in (("received: ", "received"), ("result: ", "result")):
            if msg.startswith(prefix):
                try:
                    obj = json.loads(msg[len(prefix):])
                except ValueError:
                    return
                cid = obj.get("id") if isinstance(obj, dict) else None
                with self.lock:
                    c = self.commands.get(cid)
                    if c is not None and c.get(field) is None:
                        c[field] = {"at": m.group(1) if m else "", "data": obj}

    def send(self, cmd):
        token = os.environ.get("NOTEHUB_API_KEY")
        if not token:
            return {"ok": False, "error": "NOTEHUB_API_KEY not set (env var or --env file)"}
        cmd.setdefault("id", uuid.uuid4().hex[:8])
        if cmd.get("type") in ("route", "navigate"):
            cmd.setdefault("issuedAt", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"))
        project = os.environ.get("PROJECT_UID", DEFAULT_PROJECT_UID)
        device = os.environ.get("DEVICE_UID", DEFAULT_DEVICE_UID)
        url = f"{API}/v1/projects/{project}/devices/{device}/notes/commands.qi"
        status, text = http("POST", url, token, {"body": cmd})
        entry = {"id": cmd["id"], "cmd": cmd, "sent_at": time.time(), "http": status, "http_text": text[:300],
                 "received": None, "result": None, "cloud_ack": None}
        with self.lock:
            self.commands[cmd["id"]] = entry
        self.add_line(f"[panel] sent {json.dumps(cmd)[:300]} -> HTTP {status} {text[:200]}")
        return {"ok": status == 200, "id": cmd["id"], "http": status, "text": text[:300]}

    def check_acks(self):
        wait = ACK_CHECK_MIN_GAP - (time.time() - self.last_ack_check)
        if wait > 0:
            return {"ok": False, "error": f"wait {wait:.0f} s (Notehub rate limit)"}
        self.last_ack_check = time.time()
        token = os.environ.get("NOTEHUB_API_KEY", "")
        project = os.environ.get("PROJECT_UID", DEFAULT_PROJECT_UID)
        device = os.environ.get("DEVICE_UID", DEFAULT_DEVICE_UID)
        url = f"{API}/v1/projects/{project}/events?deviceUID={device}&files=acks.qo&sortOrder=desc&pageSize=50"
        status, text = http("GET", url, token)
        if status != 200:
            return {"ok": False, "error": f"HTTP {status} {text[:200]}"}
        try:
            events = (json.loads(text) if text.strip() else {}).get("events") or []
        except ValueError:
            events = []  # Notehub once returned an empty non-JSON 200: treat as "no events yet"
        found = 0
        with self.lock:
            for ev in events:
                body = ev.get("body") or {}
                c = self.commands.get(body.get("id"))
                if c is not None and c["cloud_ack"] is None:
                    c["cloud_ack"] = body
                    found += 1
        return {"ok": True, "events": len(events), "matched": found}

    def snapshot(self, since):
        with self.lock:
            lines = [(s, t) for s, t in self.lines if s > since]
            cmds = list(self.commands.values())[-30:]
        return {"seq": self.seq, "lines": lines, "commands": cmds[::-1], "link": self.link, "pi": self.pi,
                "now": time.time(), "has_token": bool(os.environ.get("NOTEHUB_API_KEY"))}


def http(method, url, token, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as rsp:
            return rsp.status, rsp.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")
    except (urllib.error.URLError, OSError) as e:
        return 0, f"network error: {getattr(e, 'reason', e)}"


def make_handler(panel):
    page = open(os.path.join(HERE, "index.html"), "rb").read()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, obj, code=200):
            data = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/":
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(page)
            elif self.path.startswith("/api/state"):
                since = int(self.path.partition("since=")[2] or 0)
                self.reply(panel.snapshot(since))
            else:
                self.reply({"error": "not found"}, 404)

        def do_POST(self):
            # A custom header can't be sent cross-site without a CORS preflight (which we never allow),
            # so other web pages can't use this panel to send commands.
            if self.headers.get("X-Panel") != "1":
                return self.reply({"error": "forbidden"}, 403)
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                return self.reply({"ok": False, "error": "bad JSON"}, 400)
            if self.path == "/api/send":
                if not isinstance(body, dict) or not body.get("type"):
                    return self.reply({"ok": False, "error": "command needs a 'type'"}, 400)
                self.reply(panel.send(body))
            elif self.path == "/api/check-acks":
                self.reply(panel.check_acks())
            elif self.path in ("/api/logger/start", "/api/logger/stop"):
                action = self.path.rsplit("/", 1)[1]
                rc, out = panel.run(f"{REMOTE_DIR}/cellular_logger.sh {action}", timeout=30)
                panel.add_line(f"[panel] logger {action}: {out.splitlines()[0] if out else rc}")
                self.reply({"ok": rc == 0, "output": out})
            else:
                self.reply({"error": "not found"}, 404)

    return Handler


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env", default=os.path.join(HERE, ".env"),
                    help="file with NOTEHUB_API_KEY=... (default: .env next to panel.py); env vars win")
    ap.add_argument("--ssh-host", default="robot", help="ssh host for the Pi; '' runs commands locally (testing on the Pi)")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()

    loaded = load_env(os.path.expanduser(args.env))
    ssh = []
    if args.ssh_host:
        ssh = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
               "-o", "ServerAliveInterval=5", "-o", "ServerAliveCountMax=3", args.ssh_host]
    panel = Panel(ssh)
    threading.Thread(target=panel.follow_log, daemon=True).start()
    threading.Thread(target=panel.poll_pi, daemon=True).start()
    print(f"env file: {args.env} ({'loaded' if loaded else 'not found'}); "
          f"NOTEHUB_API_KEY {'set' if os.environ.get('NOTEHUB_API_KEY') else 'MISSING'}")
    print(f"Pi via: {shlex.join(ssh) if ssh else 'local shell'}")
    print(f"open http://127.0.0.1:{args.port}  (Ctrl-C to quit)")
    ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(panel)).serve_forever()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
