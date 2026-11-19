"""Tests for the robot's app link: delivery.py (the rules) and app_link.py (the HTTP exchange, against fake_app.py).

    python3 -m pytest nav/tests -q          (no robot, no network)
"""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import app_link                                  # noqa: E402
import delivery as dlv                           # noqa: E402
from fake_app import FakeApp, iso                # noqa: E402

LEGS = [{"to": "pickup", "polyline": [[-86.9115, 40.4286], [-86.9114, 40.4287]]},
        {"to": "destination", "polyline": [[-86.9114, 40.4287], [-86.9116, 40.4276]]}]
JOB = {"deliveryId": "d1", "profile": "foot-walking", "legs": LEGS}
N = [0]


def cmd(typ, body, cid=None, age=0.0):
    N[0] += 1
    return {"id": cid or f"{typ}-{N[0]}", "type": typ, "issuedAt": iso(time.time() - age), "body": body}


def now():
    return iso(time.time())


def quiet(path=None):
    return dlv.Delivery(path, log=lambda *a: None)


def states(d):
    return [n["body"]["state"] for n in d.outbox]


# ---------------------------------------------------------------- the rules (delivery.py)
def test_full_delivery_reports_every_state():
    d = quiet()
    assert d.handle(cmd("delivery", JOB), now())["ok"]
    assert d.current_leg() == (0, [(40.4286, -86.9115), (40.4287, -86.9114)])      # [lon, lat] -> (lat, lon)
    d.arrived_at_stop()
    assert not d.may_drive()
    assert d.handle(cmd("unlock", {"deliveryId": "d1"}), now())["result"] == "unlocked"
    d.handle(cmd("lock", {"deliveryId": "d1"}), now())
    assert d.current_leg()[0] == 1
    d.arrived_at_stop()
    d.handle(cmd("unlock", {"deliveryId": "d1"}), now())
    d.handle(cmd("lock", {"deliveryId": "d1"}), now())
    assert d.state == "IDLE" and d.delivery_id is None
    assert states(d) == ["EN_ROUTE_PICKUP", "AWAITING_LOAD", "AWAITING_LOAD", "AWAITING_LOAD", "EN_ROUTE_DESTINATION",
                         "ARRIVED", "ARRIVED", "ARRIVED", "COMPLETED", "IDLE"]           # incl. the two lid changes


def test_unlock_only_when_stopped():
    d = quiet()
    d.handle(cmd("delivery", JOB), now())
    a = d.handle(cmd("unlock", {"deliveryId": "d1"}), now())
    assert a == {"id": a["id"], "type": "unlock", "ok": False, "error": dlv.NOT_STOPPED} and d.lid.state == "locked"


def test_lock_without_unlock_stays_at_the_pickup():                  # 7-2
    d = quiet()
    d.handle(cmd("delivery", JOB), now())
    d.arrived_at_stop()
    assert d.handle(cmd("lock", {"deliveryId": "d1"}), now())["ok"] and d.state == "AWAITING_LOAD"


def test_refusals():
    d = quiet()
    assert not d.handle(cmd("delivery", {"deliveryId": "x", "legs": LEGS[:1]}), now())["ok"]
    assert not d.handle(cmd("delivery", {"deliveryId": "x"}), now())["ok"]
    d.handle(cmd("delivery", JOB), now())
    assert d.handle(cmd("delivery", dict(JOB, deliveryId="d2")), now())["error"].startswith("busy")
    d.arrived_at_stop()
    assert d.handle(cmd("unlock", {"deliveryId": "d2"}), now())["error"] == "not the current delivery"
    assert not d.handle(cmd("dance", {}), now())["ok"]
    assert d.handle(cmd("route", {}), now())["ok"]


def test_stale():
    d = quiet()
    assert d.handle(cmd("delivery", JOB, age=601), now())["error"].startswith("stale")
    assert d.handle(cmd("delivery", JOB, age=30), now())["ok"]
    d.arrived_at_stop()
    assert d.handle(cmd("unlock", {"deliveryId": "d1"}, age=61), now())["error"].startswith("stale")
    assert d.handle(cmd("unlock", {"deliveryId": "d1"}, age=5), now())["ok"]


def test_repeat_is_answered_not_rerun():
    d = quiet()
    c = cmd("delivery", JOB)
    first = d.handle(c, now())
    d.arrived_at_stop()
    assert d.handle(c, now()) == dict(first, duplicate=True) and d.state == "AWAITING_LOAD"


def test_fault():
    d = quiet()
    d.handle(cmd("delivery", JOB), now())
    d.set_fault("motor stalled 4 times")
    assert d.telemetry()["state"] == "FAULT" and d.telemetry()["fault"] == "motor stalled 4 times"
    d.arrived_at_stop()                                               # the next normal state clears it
    assert d.telemetry()["state"] == "AWAITING_LOAD" and "fault" not in d.telemetry()


def test_restart_resumes(tmp_path):
    f = str(tmp_path / "delivery.json")
    d = quiet(f)
    c = cmd("delivery", JOB)
    d.handle(c, now())
    d.arrived_at_stop()
    r = quiet(f)                                                      # what follow.py does after a restart
    assert r.state == "AWAITING_LOAD" and r.delivery_id == "d1" and len(r.outbox) == 2
    assert r.handle(c, now())["duplicate"]
    (tmp_path / "bad.json").write_text("{not json")
    assert quiet(str(tmp_path / "bad.json")).state == "IDLE"


def test_parse_time():
    assert dlv.parse_time("2026-11-18T12:00:00Z") == pytest.approx(1795003200.0)
    assert dlv.parse_time("2026-11-18T12:00:00.250+00:00") == pytest.approx(1795003200.25)
    assert dlv.parse_time(1795003200) == 1795003200.0
    assert dlv.parse_time(1795003200123) == pytest.approx(1795003200.123)
    assert dlv.parse_time("nonsense") is None and dlv.parse_time(None) is None


# ---------------------------------------------------------------- the exchange (app_link.py), against fake_app.py
@pytest.fixture
def app():
    a = FakeApp(poll_seconds=0.2)
    yield a
    a.close()


def wait(pred, s=5.0):
    end = time.monotonic() + s
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.05)
    return False


def start(app, d, token="test"):
    link = app_link.AppLink(d, app.url, token, poll_s=0.2)
    link.start()
    return link


def test_token(tmp_path, monkeypatch):
    monkeypatch.delenv("ROBOT_API_TOKEN", raising=False)
    f = tmp_path / "robot.env"
    f.write_text("# robot\nCOSMO_FLAGS=\"--avoid\"\nROBOT_API_TOKEN=abc123\n")
    assert app_link.load_token(str(f)) == "abc123"
    with pytest.raises(SystemExit):
        app_link.load_token(str(tmp_path / "missing.env"))


def test_nat64():
    assert app_link.nat64("76.76.21.21") == "64:ff9b::4c4c:1515"
    assert app_link.nat64("108.59.49.226") == "64:ff9b::6c3b:31e2"       # the RTK caster, as in follow.py's NTRIP code


def test_whole_delivery_over_http(app):
    d = quiet()
    link = start(app, d)
    try:
        assert wait(lambda: app.telemetry())                              # it reports its state even when idle
        app.add("delivery", JOB)
        assert wait(lambda: d.state == "EN_ROUTE_PICKUP")
        with d.lock:
            d.pos = (40.4287, -86.9114)
            d.arrived_at_stop()
        assert wait(lambda: app.telemetry()[-1]["state"] == "AWAITING_LOAD" and app.telemetry()[-1]["lat"] == 40.4287)
        app.add("unlock", {"deliveryId": "d1"})
        app.add("lock", {"deliveryId": "d1"})
        assert wait(lambda: d.state == "EN_ROUTE_DESTINATION")
        with d.lock:
            d.arrived_at_stop()
        app.add("unlock", {"deliveryId": "d1"})
        assert wait(lambda: d.lid.state == "unlocked")
        app.add("lock", {"deliveryId": "d1"})
        assert wait(lambda: app.telemetry()[-1]["state"] == "IDLE" and not d.outbox)
        seen = [t["state"] for t in app.telemetry()]
        for s in ("EN_ROUTE_PICKUP", "AWAITING_LOAD", "EN_ROUTE_DESTINATION", "ARRIVED", "COMPLETED"):
            assert s in seen                                               # every state reached the app
        assert all(c["acked"] for c in app.commands) and len(app.acks()) == 5
        assert all(a["ok"] for a in app.acks())
    finally:
        link.stop()


def test_failed_post_loses_nothing(app):
    d = quiet()
    link = start(app, d)
    try:
        assert wait(lambda: app.polls > 0)
        app.fail_uplinks = 3                                               # the next 3 POSTs fail
        app.add("delivery", JOB)
        assert wait(lambda: d.state == "EN_ROUTE_PICKUP")
        assert wait(lambda: app.fail_uplinks == 0 and app.commands[0]["acked"], 8)
        assert len(app.acks()) == 1 and app.acks()[0]["duplicate"]         # re-acked after the failures, run once
        assert "EN_ROUTE_PICKUP" in [t["state"] for t in app.telemetry()]
    finally:
        link.stop()


def test_wrong_token_and_link_loss(app):
    bad = start(app, quiet(), token="wrong")
    try:
        assert wait(lambda: "401" in bad.status) and bad.age() == float("inf")
    finally:
        bad.stop()
    link = start(app, quiet())
    try:
        assert wait(lambda: link.age() < 0.5)
        app.offline = True
        time.sleep(1.5)
        assert link.age() > 1.0 and link.status.startswith("error")
        app.offline = False
        assert wait(lambda: link.age() < 0.5)
    finally:
        link.stop()


def test_https_and_nat64_fallback(tmp_path, monkeypatch):
    """The real app is HTTPS. Check the certificate is verified for the app's name, both connecting normally and
    through the NAT64 fallback (simulated: the normal connect fails, the 'NAT64 address' is this machine)."""
    import socket
    import ssl
    import subprocess
    cert, key = str(tmp_path / "cert.pem"), str(tmp_path / "key.pem")
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=localhost",
                    "-addext", "subjectAltName=DNS:localhost", "-keyout", key, "-out", cert], check=True, capture_output=True)
    app = FakeApp(tls=(cert, key))
    try:
        trust = ssl.create_default_context(cafile=cert)
        conn = app_link.Https("localhost", app.port, timeout=5, context=trust)
        conn.request("GET", "/api/robot/inbox", headers={"Authorization": "Bearer test"})
        assert conn.getresponse().status == 200

        real = socket.create_connection
        tried = []

        def no_direct_route(addr, *a, **k):
            tried.append(addr[0])
            if addr[0] == "localhost":
                raise OSError(101, "Network is unreachable")      # what an IPv6-only hotspot does to an IPv4 site
            return real(addr, *a, **k)
        monkeypatch.setattr(socket, "create_connection", no_direct_route)
        monkeypatch.setattr(app_link, "nat64", lambda ip4: "127.0.0.1")
        conn = app_link.Https("localhost", app.port, timeout=5, context=trust)
        conn.request("GET", "/api/robot/inbox", headers={"Authorization": "Bearer test"})
        assert conn.getresponse().status == 200 and tried == ["localhost", "127.0.0.1"]

        conn = app_link.Https("localhost", app.port, timeout=5)  # untrusted certificate: must be refused
        with pytest.raises(ssl.SSLCertVerificationError):
            conn.request("GET", "/api/robot/inbox")
    finally:
        app.close()
