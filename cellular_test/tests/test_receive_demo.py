from collections import OrderedDict

import pytest

from fake_notecard import FakeNotecard
from notecard_link import NotecardLink
from receive_demo import SessionWatchdog, dispatch_command, handle_route, parse_issued_at, poll_once


def recording_handlers():
    calls = []

    def handler(cmd):
        calls.append(cmd)
        return "handled"

    return {"navigate": handler, "stop": handler}, calls


# --- dispatch_command --------------------------------------------------------

def test_dispatch_valid_command_calls_handler():
    handlers, calls = recording_handlers()
    cmd = {"id": "abc", "type": "navigate", "body": {"lat": 40.42, "lon": -86.91}}

    result = dispatch_command(cmd, handlers)

    assert result == {"id": "abc", "type": "navigate", "ok": True, "result": "handled"}
    assert calls == [cmd]


def test_dispatch_body_is_optional():
    handlers, calls = recording_handlers()
    assert dispatch_command({"id": "s1", "type": "stop"}, handlers)["ok"] is True
    assert len(calls) == 1


@pytest.mark.parametrize(
    "bad, reason",
    [
        ("not a dict", "not a JSON object"),
        ([], "not a JSON object"),
        ({}, "missing 'id'"),
        ({"type": "navigate"}, "missing 'id'"),
        ({"id": 5, "type": "navigate"}, "missing 'id'"),
        ({"id": "x"}, "missing 'type'"),
        ({"id": "x", "type": ""}, "missing 'type'"),
        ({"id": "x", "type": "navigate", "body": [1, 2]}, "'body' must be an object"),
        ({"id": "x", "type": "self_destruct"}, "unknown type"),
    ],
)
def test_dispatch_rejects_malformed(bad, reason):
    handlers, calls = recording_handlers()
    result = dispatch_command(bad, handlers)
    assert result["ok"] is False
    assert reason in result["error"]
    assert calls == []


def test_dispatch_handler_exception_is_reported_not_raised():
    def boom(cmd):
        raise ValueError("lat out of range")

    result = dispatch_command({"id": "a", "type": "navigate"}, {"navigate": boom})
    assert result["ok"] is False
    assert "lat out of range" in result["error"]


# --- poll_once ---------------------------------------------------------------

def test_poll_once_dispatches_and_acks_each_command():
    card = FakeNotecard({
        "note.changes": {"notes": {
            "a": {"body": {"id": "abc", "type": "navigate", "body": {"lat": 1, "lon": 2}}, "time": 1},
            "b": {"body": {"garbage": True}, "time": 2},
        }},
    })
    handlers, calls = recording_handlers()

    results = poll_once(NotecardLink(card), handlers, ack=True)

    assert [r["ok"] for r in results] == [True, False]
    assert len(calls) == 1
    acks = [r for r in card.requests if r["req"] == "note.add"]
    assert [a["file"] for a in acks] == ["acks.qo", "acks.qo"]
    assert acks[0]["body"]["id"] == "abc" and acks[0]["body"]["ok"] is True
    assert acks[1]["body"]["ok"] is False


def test_poll_once_without_ack_sends_nothing():
    card = FakeNotecard({"note.changes": {"notes": {"a": {"body": {"id": "1", "type": "stop"}, "time": 1}}}})
    handlers, _ = recording_handlers()
    poll_once(NotecardLink(card), handlers, ack=False)
    assert [r["req"] for r in card.requests] == ["note.changes"]


def test_poll_once_empty_queue():
    card = FakeNotecard({"note.changes": {"err": "notefile does not exist {note-noexist}"}})
    assert poll_once(NotecardLink(card), {}, ack=True) == []
    assert [r["req"] for r in card.requests] == ["note.changes"]


# --- route -------------------------------------------------------------------

NOW = parse_issued_at("2026-09-25T20:31:00.000Z")


def route_cmd(**over):
    cmd = {
        "id": "b7f3",
        "type": "route",
        "issuedAt": "2026-09-25T20:30:00.000Z",
        "body": {
            "destination": {"lat": 40.4270, "lon": -86.9135},
            "profile": "foot-walking",
            "distanceMeters": 812,
            "durationSeconds": 585,
            "polyline": [[-86.9194, 40.4283], [-86.9160, 40.4278], [-86.9135, 40.4270]],
        },
    }
    cmd.update(over)
    return cmd


def test_route_contract_example_is_handled(capsys):
    result = dispatch_command(route_cmd(), {"route": handle_route}, now=NOW)
    assert result == {"id": "b7f3", "type": "route", "ok": True, "result": "logged"}
    out = capsys.readouterr().out
    assert "lat=40.427 lon=-86.9135" in out
    assert "polyline 3 pts" in out
    assert "end lat=40.427 lon=-86.9135" in out  # [lon, lat] read in the right order


def test_route_polyline_is_optional():
    cmd = route_cmd()
    del cmd["body"]["polyline"]
    assert dispatch_command(cmd, {"route": handle_route}, now=NOW)["ok"] is True


@pytest.mark.parametrize(
    "body, reason",
    [
        ({}, "destination"),
        ({"destination": {"lat": "40.4", "lon": -86.9}}, "destination.lat must be a number"),
        ({"destination": {"lat": 140.0, "lon": -86.9}}, "out of range"),
        ({"destination": {"lat": 40.4, "lon": -86.9}, "polyline": [[1, 2, 3]]}, "[lon, lat] pairs"),
        # [lat, lon] by mistake still parses as numbers; only catchable when lat lands outside +-90
        ({"destination": {"lat": 40.4, "lon": -86.9}, "polyline": [[40.4, -186.9]]}, "out of range"),
    ],
)
def test_route_bad_body_is_acked_not_raised(body, reason):
    result = dispatch_command(route_cmd(body=body), {"route": handle_route}, now=NOW)
    assert result["ok"] is False
    assert reason in result["error"]


def test_route_older_than_limit_is_stale_and_not_acted_on():
    handlers, calls = recording_handlers()
    handlers["route"] = handlers["navigate"]
    old = route_cmd(issuedAt="2026-09-25T20:15:00Z")  # 16 min before NOW
    assert dispatch_command(old, handlers, now=NOW) == {"id": "b7f3", "type": "route", "ok": False, "error": "stale"}
    assert calls == []


@pytest.mark.parametrize("issued, reason", [(None, "missing 'issuedAt'"), ("yesterday", "invalid 'issuedAt'"), ("2026-09-25T20:30:00", "invalid 'issuedAt'")])
def test_route_needs_valid_issued_at(issued, reason):
    cmd = route_cmd()
    if issued is None:
        del cmd["issuedAt"]
    else:
        cmd["issuedAt"] = issued
    result = dispatch_command(cmd, {"route": handle_route}, now=NOW)
    assert result["ok"] is False and reason in result["error"]


def test_navigate_stale_only_when_issued_at_given():
    handlers, _ = recording_handlers()
    nav = {"id": "n", "type": "navigate", "body": {"lat": 1, "lon": 2}}
    assert dispatch_command(nav, handlers, now=NOW)["ok"] is True
    old = dict(nav, issuedAt="2026-09-25T20:29:00Z")  # 2 min old, limit 60 s
    assert dispatch_command(old, handlers, now=NOW)["error"] == "stale"


def test_stop_is_never_stale():
    handlers, _ = recording_handlers()
    cmd = {"id": "s", "type": "stop", "issuedAt": "2020-01-01T00:00:00Z"}
    assert dispatch_command(cmd, handlers, now=NOW)["ok"] is True


# --- dedupe ------------------------------------------------------------------

def test_duplicate_id_acts_once_but_acks_both():
    note = {"body": {"id": "abc", "type": "navigate", "body": {"lat": 1, "lon": 2}}, "time": 1}
    card = FakeNotecard({"note.changes": [{"notes": {"a": note}}, {"notes": {"b": note}}]})
    link = NotecardLink(card)
    handlers, calls = recording_handlers()
    seen = OrderedDict()

    first = poll_once(link, handlers, seen=seen, now=NOW)
    second = poll_once(link, handlers, seen=seen, now=NOW)

    assert len(calls) == 1
    assert first[0]["ok"] is True and "duplicate" not in first[0]
    assert second[0] == dict(first[0], duplicate=True)
    acks = [r["body"] for r in card.requests if r["req"] == "note.add"]
    assert [a["id"] for a in acks] == ["abc", "abc"]


def test_seen_ids_are_bounded(monkeypatch):
    import receive_demo

    monkeypatch.setattr(receive_demo, "SEEN_IDS_MAX", 2)
    notes = {str(i): {"body": {"id": f"id{i}", "type": "stop"}, "time": i} for i in range(3)}
    seen = OrderedDict()
    poll_once(NotecardLink(FakeNotecard({"note.changes": {"notes": notes}})), recording_handlers()[0], seen=seen)
    assert list(seen) == ["id1", "id2"]


# --- session watchdog --------------------------------------------------------

OPEN = {"status": "connected (session open) {connected}"}
CLOSED = {"status": "connected {connected-closed}"}


def run_watchdog(statuses, times):
    card = FakeNotecard({"hub.status": statuses})
    clock = iter(times)
    dog = SessionWatchdog(NotecardLink(card), check_every=15, closed_grace=30, retry_every=120, clock=lambda: next(clock))
    fired = [dog.tick() for _ in times]
    return fired, [r["req"] for r in card.requests if r["req"] == "hub.sync"]


def test_watchdog_leaves_open_session_alone():
    fired, syncs = run_watchdog([OPEN], [0, 15, 30, 45, 60])
    assert fired == [False] * 5 and syncs == []


def test_watchdog_syncs_after_grace_then_waits_retry_interval():
    fired, syncs = run_watchdog([CLOSED], [0, 15, 30, 45, 60, 150, 165])
    # closed at 0; grace passes at 30 -> sync; 45/60 within retry window; 150 -> retry
    assert fired == [False, False, True, False, False, True, False]
    assert len(syncs) == 2


def test_watchdog_resets_when_session_reopens():
    fired, syncs = run_watchdog([CLOSED, OPEN, CLOSED, CLOSED, CLOSED], [0, 15, 30, 45, 60])
    # reopened at 15 resets the timer; closed again from 30, so grace ends at 60
    assert fired == [False, False, False, False, True]


def test_watchdog_only_checks_every_interval():
    card = FakeNotecard({"hub.status": [OPEN]})
    clock = iter([0, 1, 2, 16])
    dog = SessionWatchdog(NotecardLink(card), clock=lambda: next(clock))
    for _ in range(4):
        dog.tick()
    assert [r["req"] for r in card.requests] == ["hub.status", "hub.status"]
