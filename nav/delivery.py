"""The robot's side of a delivery (claude/delivery-contract.md in the project). No networking, no hardware.

    IDLE -> delivery -> EN_ROUTE_PICKUP -> (end of leg 1) -> AWAITING_LOAD
         -> unlock, lock (vendor) -> EN_ROUTE_DESTINATION -> (end of leg 2) -> ARRIVED
         -> unlock, lock (customer) -> COMPLETED -> IDLE
    cancel (operator cleared it in the app): any state -> IDLE

app_link.py calls handle() for each command from the app; follow.py calls arrived_at_stop() at the end of a leg and
reads current_leg(). Every change (state, lid, fault) adds a telemetry note to `outbox`, which app_link.py sends and
clears once the app has it, and saves the delivery to disk so a restart carries on with it.
Both threads use it, so they hold `lock` while they do.
"""
import json
import os
import threading
import time
import uuid

DRIVING = ("EN_ROUTE_PICKUP", "EN_ROUTE_DESTINATION")
STOPS = ("AWAITING_LOAD", "ARRIVED")
LEG_OF = {"EN_ROUTE_PICKUP": 0, "AWAITING_LOAD": 0, "EN_ROUTE_DESTINATION": 1, "ARRIVED": 1}
STALE_S = {"delivery": 600, "cancel": 600, "unlock": 60, "lock": 60, "state": 60}
NOT_STOPPED = "not stopped at the pickup or destination"


def note(kind, body):
    """One message to the app. The id lets the app store it once even if it is sent twice."""
    return {"id": str(uuid.uuid4()), "kind": kind, "body": body}


def parse_time(v):
    """App time (ISO 8601, Unix s or Unix ms) -> Unix s, or None."""
    if isinstance(v, (int, float)):
        return v / 1000 if v > 1e11 else float(v)
    try:
        from datetime import datetime
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


class Lid:
    """The compartment latch: the servo on the team PCB's J17, driven by the motor firmware (`servo open` / `servo close`
    over the STM32 link, robot_drive.Stm32.servo). Unlocked = open (2050 us), locked = closed (1700 us); the firmware
    ramps the move (~10 s). Without a latch (tests, the simulator, app_check.py) it only prints, as before."""
    state = "locked"

    def __init__(self, latch=None, log=print):
        self.latch = latch if hasattr(latch, "servo") else None
        self.log = log

    def set(self, state):
        """Move the latch to "locked" / "unlocked". True once the STM32 confirmed (or with no latch fitted)."""
        if self.latch is None:
            print(f"LATCH (no servo connected): {state}", flush=True)
            self.state = state
            return True
        r = self.latch.servo("close" if state == "locked" else "open")
        if r is None:
            self.log(f"app: latch did not confirm '{state}' (no reply from the STM32)")
            return False
        self.log(f"app: latch -> {state} (servo {r['cur']} -> {r['target']} us)")
        self.state = state
        return True

    def apply(self):
        """Send the current state to the latch, e.g. after a restart, when the servo isn't being driven yet."""
        if self.latch is not None:
            r = self.latch.servo("close" if self.state == "locked" else "open")
            self.log(f"app: latch set to {self.state} at start" + ("" if r else " FAILED (no reply from the STM32)"))


class Delivery:
    def __init__(self, path=None, log=print, latch=None):
        self.lock = threading.RLock()
        self.path, self.log = path, log
        self.lid = Lid(latch, log)
        self.state, self.job, self.leg, self.opened, self.fault = "IDLE", None, None, False, None
        self.acks = {}                  # command id -> its ack, so a repeated command isn't run twice
        self.pos = (None, None)         # (lat, lon), kept up to date by follow.py
        self.outbox = []                # telemetry notes not yet delivered to the app
        self.history = []               # for the run log
        if path and os.path.exists(path):
            self.load()
        self.lid.apply()                # the servo isn't driven after a reboot: put the latch where the state says

    # ---------------------------------------------------------------- what follow.py asks
    @property
    def delivery_id(self):
        return self.job["deliveryId"] if self.job else None

    def may_drive(self):
        return self.state in DRIVING

    def current_leg(self):
        """(0 or 1, [(lat, lon), ...]) while driving, else None. The app's polylines are [lon, lat]."""
        if not self.may_drive():
            return None
        return self.leg, [(p[1], p[0]) for p in self.job["legs"][self.leg]["polyline"]]

    def destination(self):
        """(lat, lon) of the destination pin the app sent, while driving the destination leg, else None."""
        d = self.job.get("destination") if self.state == "EN_ROUTE_DESTINATION" else None
        return (d["lat"], d["lon"]) if d else None

    def waiting_for(self):
        return {"IDLE": "waiting for a delivery from the app",
                "AWAITING_LOAD": "at the pickup: waiting for the vendor to load and lock",
                "ARRIVED": "at the destination: waiting for the customer"}.get(self.state, "")

    def telemetry(self):
        t = {"deliveryId": self.delivery_id, "state": "FAULT" if self.fault else self.state,
             "lat": self.pos[0], "lon": self.pos[1], "lock": self.lid.state}
        if self.fault:
            t["fault"] = self.fault
        return t

    # ---------------------------------------------------------------- what follow.py tells it
    def arrived_at_stop(self):
        if self.state == "EN_ROUTE_PICKUP":
            self._set("AWAITING_LOAD")
        elif self.state == "EN_ROUTE_DESTINATION":
            self._set("ARRIVED")

    def set_fault(self, why):
        if self.fault != why:
            self.fault = why
            self._changed(f"FAULT: {why}")

    def clear_fault(self):
        if self.fault:
            self.fault = None
            self._changed("fault cleared")

    # ---------------------------------------------------------------- commands from the app
    def handle(self, cmd, server_now):
        """The ack for one command: {id, type, ok, result | error}. A repeat gets the first answer + duplicate."""
        cid, typ, body = cmd.get("id"), cmd.get("type"), cmd.get("body") or {}
        if cid in self.acks:
            return dict(self.acks[cid], duplicate=True)
        issued, now = parse_time(cmd.get("issuedAt")), parse_time(server_now)
        if typ in STALE_S and issued and now and now - issued > STALE_S[typ]:
            ok, out = False, f"stale: issued {now - issued:.0f} s ago"
        elif typ == "delivery":
            ok, out = self._delivery(body)
        elif typ == "cancel":
            ok, out = self._cancel(body)
        elif typ == "state":
            ok, out = self._force(body)
        elif typ in ("unlock", "lock") and (not self.job or body.get("deliveryId") != self.delivery_id):
            ok, out = False, "not the current delivery"
        elif typ == "unlock":
            ok, out = self._unlock()
        elif typ == "lock":
            ok, out = self._lock()
        elif typ == "route":
            ok, out = True, "received (operator link test, not driven)"
        else:
            ok, out = False, f"unknown command {typ!r}"
        self.acks[cid] = {"id": cid, "type": typ, "ok": ok, ("result" if ok else "error"): out}
        self.history.append((round(time.time(), 1), f"{typ}: {'ok' if ok else out}"))
        self.log(f"app: {typ} -> {'ok' if ok else 'refused: ' + out}")
        self.save()
        return self.acks[cid]

    def _delivery(self, job):
        if self.state != "IDLE":
            return False, f"busy: delivery {self.delivery_id} is {self.state}"
        try:
            ok = len(job["legs"]) == 2 and all(len(lg["polyline"]) >= 2 and all(len(p) == 2 for p in lg["polyline"])
                                               for lg in job["legs"])
        except (KeyError, TypeError):
            ok = False
        if not ok:
            return False, "bad delivery: needs 2 legs, each a polyline of [lon, lat] points"
        self.job, self.leg, self.opened = job, 0, False
        self._set("EN_ROUTE_PICKUP")
        return True, self.state

    def _cancel(self, body):
        """The app cleared this delivery (operator): drop it and go back to IDLE, wherever the robot is.
        force: drop whatever job it holds, even another one (the operator wants the robot free)."""
        if not self.job or (body.get("deliveryId") != self.delivery_id and body.get("force") is not True):
            return True, "nothing to cancel"
        self.job = self.leg = None
        self.opened = False
        self._set("IDLE")
        return True, self.state

    def _force(self, body):
        """Operator override from the app: go straight to this state of the current delivery (IDLE drops it).
        It never drives with the lid open: a driving state locks it first, and IDLE tries to."""
        state = body.get("state")
        if not self.job or body.get("deliveryId") != self.delivery_id:
            return False, "not the current delivery"
        if state not in LEG_OF and state != "IDLE":
            return False, f"unknown state {state!r}"
        if state in DRIVING and not self._set_lid("locked"):
            return False, "latch did not respond"
        if state == "IDLE":
            self._set_lid("locked")
            self.job = self.leg = None
        else:
            self.leg = LEG_OF[state]
        self.opened = False
        self._set(state)
        return True, self.state

    def _unlock(self):
        if self.state not in STOPS:
            return False, NOT_STOPPED
        if not self._set_lid("unlocked"):
            return False, "latch did not respond"
        self.opened = True
        return True, self.lid.state

    def _lock(self):
        if not self._set_lid("locked"):
            return False, "latch did not respond"
        if self.state in STOPS and self.opened and self.lid.state == "locked":   # 7-2: only once locked
            self.opened = False
            if self.state == "AWAITING_LOAD":
                self.leg = 1
                self._set("EN_ROUTE_DESTINATION")
            else:
                self._set("COMPLETED")
                self.job = self.leg = None
                self._set("IDLE")
        return True, self.lid.state

    # ---------------------------------------------------------------- every change: report it, save it
    def _set(self, state):
        self.state, self.fault = state, None              # a normal state clears a fault
        self._changed(f"state {state}")

    def _set_lid(self, state):
        """Move the lid; False if the latch didn't confirm (the state then stays as it was)."""
        if self.lid.state != state:
            if not self.lid.set(state):
                return False
            self._changed(f"lid {state}")
        return True

    def _changed(self, what):
        self.outbox.append(note("telemetry", self.telemetry()))
        self.history.append((round(time.time(), 1), what))
        self.log(f"app: {what}" + (f" ({self.delivery_id})" if self.delivery_id else ""))
        self.save()

    def save(self):
        if not self.path:
            return
        d = {k: getattr(self, k) for k in ("state", "job", "leg", "opened", "fault", "outbox")}
        d.update(lid=self.lid.state, acks=dict(list(self.acks.items())[-200:]))
        with open(self.path + ".tmp", "w") as f:
            json.dump(d, f)
        os.replace(self.path + ".tmp", self.path)      # never leaves a half-written file

    def load(self):
        try:
            d = json.load(open(self.path))
            for k in ("state", "job", "leg", "opened", "fault", "outbox", "acks"):
                setattr(self, k, d[k])
            self.lid.state = d["lid"]
        except (OSError, ValueError, KeyError) as e:
            self.log(f"app: ignoring unreadable {self.path}: {e!r}")
            return
        if self.state != "IDLE":
            self.log(f"app: resumed after a restart: {self.state} ({self.delivery_id})")
