"""Downlink test: poll commands.qi on the Notecard and dispatch each command.

Handlers only PRINT. This bring-up test never drives motors or any actuator.
"""

import argparse
import json
import os
import time
from collections import OrderedDict
from datetime import datetime, timezone

from notecard_link import NotecardError, NotecardLink, open_card

COMMANDS_FILE = "commands.qi"
ACKS_FILE = "acks.qo"

# Max age (seconds, now - issuedAt) before a command is acked "stale" and not acted on.
# route must carry issuedAt; navigate is only checked when it has one. stop/ping are never stale.
MAX_AGE_SECONDS = {"route": 600, "navigate": 60}
REQUIRES_ISSUED_AT = {"route"}
SEEN_IDS_MAX = 1000

DEFAULT_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "cellular_log.txt")
HEARTBEAT_SECONDS = 60

# Set by --log: every console line is also appended to this file, timestamped.
_log_file = None
# Card clock minus Pi clock. The Pi has no NTP without Ethernet (and no RTC battery), so log
# timestamps use the Notecard's network time; refreshed at start and on every heartbeat.
_clock_offset = 0.0


def open_log(path):
    global _log_file
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    _log_file = open(path, "a", buffering=1)


def sync_log_clock(link):
    global _clock_offset
    _clock_offset = link.now() - time.time()


def log(msg, file_only=False):
    """Print a line and append it to the log file (if open) with a UTC timestamp."""
    if not file_only:
        print(msg, flush=True)
    if _log_file is not None:
        ts = datetime.fromtimestamp(time.time() + _clock_offset, timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
        _log_file.write(f"{ts}  {msg}\n")


def heartbeat(link):
    """One status line: proves the receiver is alive and shows session state and signal."""
    sync_log_clock(link)
    hub = link.hub_status().get("status", "?")
    w = link.wireless_status().get("net") or {}
    log(f"heartbeat: hub={hub!r} bars={w.get('bars')} rssi={w.get('rssi')} rsrp={w.get('rsrp')} "
        f"sinr={w.get('sinr')} rat={w.get('rat')}")


class SessionWatchdog:
    """Reopen the Notehub session if it stays closed.

    Inbound push (hub.set sync:true) only works while hub.status shows "(session open)
    {connected}". On 2026-09-25 the session dropped to "{connected-closed}" (during Pi
    undervoltage) and did not reopen on its own, so commands sat in Notehub until a
    hub.sync. A reconnect can take ~90 s (modem power cycle), hence the retry spacing.
    """

    def __init__(self, link, check_every=15, closed_grace=30, retry_every=120, clock=time.monotonic):
        self.link, self.clock = link, clock
        self.check_every, self.closed_grace, self.retry_every = check_every, closed_grace, retry_every
        self.next_check = 0.0
        self.closed_since = None
        self.last_sync = None

    def tick(self):
        """Call from the poll loop; returns True if it asked for a hub.sync."""
        now = self.clock()
        if now < self.next_check:
            return False
        self.next_check = now + self.check_every
        status = self.link.hub_status().get("status", "")
        if "{connected}" in status:
            self.closed_since = None
            return False
        if self.closed_since is None:
            self.closed_since = now
        if now - self.closed_since < self.closed_grace:
            return False
        if self.last_sync is not None and now - self.last_sync < self.retry_every:
            return False
        log(f"session not open for {now - self.closed_since:.0f}s ({status}); forcing hub.sync")
        self.link.sync()
        self.last_sync = now
        return True


def handle_navigate(cmd):
    b = cmd.get("body", {})
    log(f"  -> [navigate] would go to lat={b.get('lat')} lon={b.get('lon')} (print only)")
    return "logged"


def _latlon(value, what):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{what} must be a number")
    return float(value)


def handle_route(cmd):
    """Contract: see APP_INTEGRATION.md. polyline points are GeoJSON [lon, lat]."""
    b = cmd.get("body") or {}
    dest = b.get("destination")
    if not isinstance(dest, dict):
        raise ValueError("body.destination must be an object with lat/lon")
    lat, lon = _latlon(dest.get("lat"), "destination.lat"), _latlon(dest.get("lon"), "destination.lon")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("destination lat/lon out of range")
    poly = b.get("polyline")
    if poly is None:
        path = "no polyline"
    else:
        if not isinstance(poly, list) or not all(isinstance(p, list) and len(p) == 2 for p in poly):
            raise ValueError("polyline must be a list of [lon, lat] pairs")
        pts = [(_latlon(p[0], "polyline lon"), _latlon(p[1], "polyline lat")) for p in poly]
        if any(not (-180 <= plon <= 180 and -90 <= plat <= 90) for plon, plat in pts):
            raise ValueError("polyline point out of range (expected [lon, lat])")
        if pts:
            (slon, slat), (elon, elat) = pts[0], pts[-1]
            path = f"polyline {len(pts)} pts, start lat={slat} lon={slon}, end lat={elat} lon={elon}"
        else:
            path = "polyline 0 pts"
    log(
        f"  -> [route] would go to lat={lat} lon={lon} ({b.get('profile')}, "
        f"{b.get('distanceMeters')} m, {b.get('durationSeconds')} s); {path} (print only)"
    )
    return "logged"


def handle_stop(cmd):
    log("  -> [stop] (print only)")
    return "logged"


def handle_ping(cmd):
    log("  -> [ping] pong")
    return "pong"


HANDLERS = {"navigate": handle_navigate, "route": handle_route, "stop": handle_stop, "ping": handle_ping}


def parse_issued_at(value):
    """UTC ISO-8601 (e.g. 2026-09-25T20:31:00.000Z) -> epoch seconds."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("issuedAt needs a timezone (use Z for UTC)")
    return dt.timestamp()


def staleness_error(cmd, now):
    """None if the command is fresh enough to act on, else the error string for its ack."""
    cmd_type = cmd["type"]
    max_age = MAX_AGE_SECONDS.get(cmd_type)
    if max_age is None:
        return None
    issued = cmd.get("issuedAt")
    if issued is None:
        return "missing 'issuedAt'" if cmd_type in REQUIRES_ISSUED_AT else None
    try:
        age = now - parse_issued_at(issued)
    except (TypeError, ValueError, AttributeError):
        return "invalid 'issuedAt' (want UTC ISO-8601)"
    return "stale" if age > max_age else None


def dispatch_command(cmd, handlers, now=None):
    """Validate one command body and route it. Never raises; returns a result dict."""
    if not isinstance(cmd, dict):
        return {"id": None, "ok": False, "error": "command is not a JSON object"}
    cmd_id = cmd.get("id")
    if not isinstance(cmd_id, str) or not cmd_id:
        return {"id": None, "ok": False, "error": "missing 'id' (non-empty string)"}
    cmd_type = cmd.get("type")
    if not isinstance(cmd_type, str) or not cmd_type:
        return {"id": cmd_id, "ok": False, "error": "missing 'type' (non-empty string)"}
    if "body" in cmd and not isinstance(cmd["body"], dict):
        return {"id": cmd_id, "type": cmd_type, "ok": False, "error": "'body' must be an object"}
    handler = handlers.get(cmd_type)
    if handler is None:
        return {"id": cmd_id, "type": cmd_type, "ok": False, "error": f"unknown type {cmd_type!r}"}
    stale = staleness_error(cmd, time.time() if now is None else now)
    if stale:
        return {"id": cmd_id, "type": cmd_type, "ok": False, "error": stale}
    try:
        return {"id": cmd_id, "type": cmd_type, "ok": True, "result": handler(cmd)}
    except Exception as e:  # report handler failures back to the cloud instead of crashing
        return {"id": cmd_id, "type": cmd_type, "ok": False, "error": f"handler failed: {e}"}


def summarize(cmd):
    """Log line for a command; long polylines are shortened to a point count."""
    body = cmd.get("body") if isinstance(cmd, dict) else None
    if isinstance(body, dict) and isinstance(body.get("polyline"), list) and len(body["polyline"]) > 4:
        body = dict(body, polyline=f"<{len(body['polyline'])} points>")
        cmd = dict(cmd, body=body)
    return json.dumps(cmd)


def poll_once(link, handlers, ack=True, seen=None, now=None):
    """Handle every pending command once. seen (OrderedDict id -> result) dedupes redeliveries:
    a repeated id is not acted on again, but is acked again with the first result."""
    results = []
    for cmd in link.receive_notes(COMMANDS_FILE):
        log(f"received: {summarize(cmd)}")
        log(f"  raw: {json.dumps(cmd)}", file_only=True)  # full note, incl. long polylines
        cmd_id = cmd.get("id") if isinstance(cmd, dict) else None
        if seen is not None and isinstance(cmd_id, str) and cmd_id in seen:
            result = dict(seen[cmd_id], duplicate=True)
            log("  duplicate id: not acting again")
        else:
            result = dispatch_command(cmd, handlers, now=now() if callable(now) else now)
            if seen is not None and isinstance(cmd_id, str) and cmd_id:
                seen[cmd_id] = result
                while len(seen) > SEEN_IDS_MAX:
                    seen.popitem(last=False)
        log(f"  result: {json.dumps(result)}")
        if ack:
            link.send_note(ACKS_FILE, result, sync=True)
        results.append(result)
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--interval", type=float, default=1.0, help="seconds between polls")
    ap.add_argument("--no-ack", action="store_true", help="don't send results to acks.qo")
    ap.add_argument("--once", action="store_true", help="poll a single time and exit")
    ap.add_argument("--log", default=DEFAULT_LOG, help=f"append everything to this text file (default: {DEFAULT_LOG})")
    ap.add_argument("--no-log", action="store_true", help="console only, no log file")
    args = ap.parse_args()

    if not args.no_log:
        open_log(args.log)
    link = NotecardLink(open_card())
    sync_log_clock(link)
    log(f"===== receiver start (pid {os.getpid()}, Pi clock {datetime.now().astimezone():%Y-%m-%d %H:%M:%S %Z}) =====")
    link.enable_immediate_sync()
    log(f"card: {link.version().get('device')}  hub: {link.hub_status().get('status')}")
    log(f"polling {COMMANDS_FILE} every {args.interval}s (Ctrl-C to stop)")
    if _log_file is not None:
        log(f"logging to {os.path.abspath(args.log)}")
    seen = OrderedDict()
    watchdog = SessionWatchdog(link)
    next_heartbeat = 0.0
    while True:
        try:
            poll_once(link, HANDLERS, ack=not args.no_ack, seen=seen, now=link.now)
            watchdog.tick()
            if time.monotonic() >= next_heartbeat:
                next_heartbeat = time.monotonic() + HEARTBEAT_SECONDS
                heartbeat(link)
        except NotecardError as e:
            log(f"notecard error: {e}")
        except OSError as e:  # I2C hiccup (e.g. brownout): log it and keep going instead of dying unattended
            log(f"I/O error talking to the card: {e!r}")
        if args.once:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("===== receiver stopped (Ctrl-C) =====")
    except Exception as e:
        hint = " (card not answering: is it wired and powered? `i2cdetect -y 1` should show 17)" if "reset Notecard" in str(e) else ""
        log(f"===== receiver crashed: {e!r}{hint} =====")
        raise
