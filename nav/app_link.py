"""The robot's connection to the Cosmo web app. The robot always calls the app (the hotspot can't take incoming
connections). Every few seconds it does one exchange:

    1. GET  /api/robot/inbox     -> {now, pollSeconds, commands: [{id, type, issuedAt, body}, ...]}
    2. run each command (delivery.py) and get its ack
    3. POST /api/robot/uplink    <- [the acks..., every change not yet delivered..., the robot's state right now]

Nothing is lost if an exchange fails: the app keeps sending a command until it gets the ack (and delivery.py answers a
repeat without running it again), changes stay in the outbox until a POST succeeds, and the state is re-sent every
time anyway. Both requests send "Authorization: Bearer <ROBOT_API_TOKEN>". Standard library only.
"""
import http.client
import ipaddress
import json
import os
import socket
import threading
import time
import urllib.parse

from delivery import note

DEFAULT_URL = "https://cosmo-beryl.vercel.app"


def load_token(path="~/.config/cosmo_robot.env"):
    """ROBOT_API_TOKEN from a KEY=VALUE file (kept out of git), or from the environment."""
    path = os.path.expanduser(path)
    if os.path.exists(path):
        for line in open(path):
            key, _, value = line.partition("=")
            if key.strip() == "ROBOT_API_TOKEN" and value.strip():
                return value.strip().strip("'\"")
    if os.environ.get("ROBOT_API_TOKEN"):
        return os.environ["ROBOT_API_TOKEN"]
    raise SystemExit(f"no robot token: put ROBOT_API_TOKEN=... in {path} (the same value as in Vercel)")


def nat64(ip4):
    """IPv4 address -> the same address through NAT64: 76.76.21.21 -> 64:ff9b::4c4c:1515 (= 64:ff9b::76.76.21.21)."""
    return str(ipaddress.ip_address(f"64:ff9b::{ip4}"))


class Https(http.client.HTTPSConnection):
    """HTTPS, plus a fallback for an IPv6-only hotspot: *.vercel.app has only IPv4 addresses, so if connecting
    normally fails, connect to the IPv4 address through the carrier's NAT64 (same idea as ntrip_rtk.py)."""

    def connect(self):
        try:
            super().connect()
        except OSError:
            ip4 = socket.getaddrinfo(self.host, self.port, socket.AF_INET)[0][4][0]
            sock = socket.create_connection((nat64(ip4), self.port), self.timeout)
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class AppLink(threading.Thread):
    def __init__(self, dm, url=DEFAULT_URL, token="", poll_s=3.0):
        super().__init__(daemon=True)
        u = urllib.parse.urlsplit(url)
        self.conn_args = (u.hostname, u.port or (443 if u.scheme == "https" else 80))
        self.conn_class = Https if u.scheme == "https" else http.client.HTTPConnection
        self.dm, self.token, self.poll_s = dm, token, poll_s
        self.last_ok = None            # time of the last good exchange
        self.status = "starting"
        self.commit = None
        self.stopped = threading.Event()

    def age(self):
        """Seconds since the last good exchange: the link-loss signal (S9-1)."""
        return float("inf") if self.last_ok is None else time.monotonic() - self.last_ok

    def stop(self):
        self.stopped.set()

    def run(self):
        while not self.stopped.is_set():
            try:
                self.exchange()
                if self.status.startswith("error"):
                    print("app link: working again", flush=True)
                self.last_ok, self.status = time.monotonic(), "ok"
            except Exception as e:                       # keep trying forever; follow.py stops the robot meanwhile
                if not self.status.startswith("error"):
                    print(f"app link: {e}", flush=True)
                self.status = f"error: {e}"
            self.stopped.wait(self.poll_s)

    def exchange(self):
        inbox = self.request("GET", "/api/robot/inbox")
        self.commit = inbox.get("commit")
        self.poll_s = float(inbox.get("pollSeconds") or self.poll_s)
        with self.dm.lock:
            acks = [note("ack", self.dm.handle(c, inbox.get("now"))) for c in inbox.get("commands") or []]
            changes = list(self.dm.outbox)
            now = note("telemetry", self.dm.telemetry())
        self.request("POST", "/api/robot/uplink", acks + changes + [now])
        if changes:
            with self.dm.lock:
                del self.dm.outbox[:len(changes)]            # delivered (new ones may have been added meanwhile)
                self.dm.save()

    def request(self, method, path, body=None):
        conn = self.conn_class(*self.conn_args, timeout=10)
        try:
            conn.request(method, path, None if body is None else json.dumps(body),
                         {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
            r = conn.getresponse()
            data = r.read()
        finally:
            conn.close()
        if r.status == 401:
            raise ConnectionError("401: the app refused the robot token")
        if not 200 <= r.status < 300:
            raise ConnectionError(f"{method} {path}: HTTP {r.status} {data[:200]!r}")
        return json.loads(data) if data else {}
