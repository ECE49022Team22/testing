import pytest

from fake_notecard import FakeNotecard
from notecard_link import NotecardError, NotecardLink


def make_link(responses=None):
    card = FakeNotecard(responses)
    return NotecardLink(card), card


# --- send_note ---------------------------------------------------------------

def test_send_note_builds_note_add_with_sync():
    link, card = make_link({"note.add": {"total": 1}})
    body = {"battery": 12.4, "lat": 40.42}

    link.send_note("telemetry.qo", body)

    assert card.requests == [
        {"req": "note.add", "file": "telemetry.qo", "body": body, "sync": True}
    ]


def test_send_note_sync_false_is_passed_through():
    link, card = make_link()
    link.send_note("acks.qo", {"id": "abc"}, sync=False)
    assert card.last == {"req": "note.add", "file": "acks.qo", "body": {"id": "abc"}, "sync": False}


def test_send_note_returns_card_response():
    link, _ = make_link({"note.add": {"total": 3}})
    assert link.send_note("telemetry.qo", {}) == {"total": 3}


def test_send_note_raises_on_card_error():
    link, _ = make_link({"note.add": {"err": "no notefile specified"}})
    with pytest.raises(NotecardError, match="no notefile"):
        link.send_note("telemetry.qo", {"x": 1})


def test_send_note_rejects_non_dict_body():
    link, card = make_link()
    with pytest.raises(TypeError):
        link.send_note("telemetry.qo", "not a dict")
    assert card.requests == []


# --- receive_notes -----------------------------------------------------------

def test_receive_notes_builds_note_changes_with_delete():
    link, card = make_link({"note.changes": {"total": 0}})
    link.receive_notes("commands.qi")
    assert card.requests == [{"req": "note.changes", "file": "commands.qi", "delete": True}]


def test_receive_notes_parses_bodies_in_order():
    rsp = {
        "changes": 2,
        "total": 2,
        "notes": {
            "1:1": {"body": {"id": "abc", "type": "navigate", "body": {"lat": 40.42, "lon": -86.91}}, "time": 100},
            "1:2": {"body": {"id": "def", "type": "stop"}, "time": 101},
        },
    }
    link, _ = make_link({"note.changes": rsp})

    assert link.receive_notes("commands.qi") == [
        {"id": "abc", "type": "navigate", "body": {"lat": 40.42, "lon": -86.91}},
        {"id": "def", "type": "stop"},
    ]


def test_receive_notes_orders_by_time_not_key():
    rsp = {"notes": {"b": {"body": {"n": 2}, "time": 200}, "a": {"body": {"n": 1}, "time": 100}}}
    link, _ = make_link({"note.changes": rsp})
    assert link.receive_notes("commands.qi") == [{"n": 1}, {"n": 2}]


@pytest.mark.parametrize("rsp", [{}, {"total": 0}, {"changes": 0, "total": 0, "notes": {}}])
def test_receive_notes_empty_returns_empty_list(rsp):
    link, _ = make_link({"note.changes": rsp})
    assert link.receive_notes("commands.qi") == []


def test_receive_notes_noexist_returns_empty_list():
    # Before anything has ever been sent to commands.qi the Notefile doesn't exist yet.
    link, _ = make_link({"note.changes": {"err": "notefile does not exist {note-noexist}"}})
    assert link.receive_notes("commands.qi") == []


def test_receive_notes_other_errors_raise():
    link, _ = make_link({"note.changes": {"err": "some other failure {io}"}})
    with pytest.raises(NotecardError):
        link.receive_notes("commands.qi")


def test_receive_notes_note_without_body_yields_empty_dict():
    # A note can carry only a payload; surface it so dispatch can reject it.
    link, _ = make_link({"note.changes": {"notes": {"x": {"payload": "AAEC", "time": 1}}}})
    assert link.receive_notes("commands.qi") == [{}]


# --- simple wrappers ---------------------------------------------------------

@pytest.mark.parametrize(
    "method, expected_req",
    [
        ("sync", {"req": "hub.sync"}),
        ("hub_status", {"req": "hub.status"}),
        ("wireless_status", {"req": "card.wireless"}),
        ("version", {"req": "card.version"}),
    ],
)
def test_wrappers_send_expected_request(method, expected_req):
    link, card = make_link({expected_req["req"]: {"ok": True}})
    assert getattr(link, method)() == {"ok": True}
    assert card.requests == [expected_req]


def test_wrapper_raises_on_error():
    link, _ = make_link({"hub.status": {"err": "boom"}})
    with pytest.raises(NotecardError):
        link.hub_status()


# --- enable_immediate_sync ---------------------------------------------------

def test_enable_immediate_sync_sets_continuous_sync():
    link, card = make_link()
    link.enable_immediate_sync()
    assert card.last == {"req": "hub.set", "mode": "continuous", "sync": True}


# --- now ---------------------------------------------------------------------

def test_now_uses_card_clock():
    link, _ = make_link({"card.time": {"time": 1790379595}})
    assert link.now() == 1790379595


def test_now_falls_back_to_pi_clock_without_card_time():
    import time

    link, _ = make_link({"card.time": {"err": "time is not yet set {no-time}"}})
    assert abs(link.now() - time.time()) < 5
