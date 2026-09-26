import json
import os

import pytest

import cloud_inject
import mqtt_watch
from fake_notecard import FakeNotecard
from notecard_link import NotecardLink
from send_demo import build_telemetry, send_telemetry


class FakeResponse:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload or {}
        self.text = json.dumps(self._payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, responses):
        self.calls = []
        self._responses = list(responses)

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self._responses.pop(0)


# --- cloud_inject ------------------------------------------------------------

def test_get_token_uses_client_credentials_form():
    s = FakeSession([FakeResponse(200, {"access_token": "tok123", "expires_in": 1800})])
    assert cloud_inject.get_token("cid", "csecret", session=s) == "tok123"
    url, kw = s.calls[0]
    assert url == "https://api.notefile.net/oauth2/token"
    assert kw["data"] == {"grant_type": "client_credentials", "client_id": "cid", "client_secret": "csecret"}


def test_inject_note_posts_wrapped_body_with_bearer():
    s = FakeSession([FakeResponse(200, {})])
    cmd = {"id": "abc", "type": "navigate", "body": {"lat": 40.42, "lon": -86.91}}

    cloud_inject.inject_note("tok", "app:proj", "dev:123", cmd, session=s)

    url, kw = s.calls[0]
    assert url == "https://api.notefile.net/v1/projects/app:proj/devices/dev:123/notes/commands.qi"
    assert kw["headers"]["Authorization"] == "Bearer tok"
    assert kw["json"] == {"body": cmd}


def test_inject_note_raises_on_http_error():
    s = FakeSession([FakeResponse(401, {"err": "unauthorized"})])
    with pytest.raises(RuntimeError):
        cloud_inject.inject_note("tok", "p", "d", {"id": "x", "type": "stop"}, session=s)


AUTH_ENV = ("NOTEHUB_API_KEY",) + cloud_inject.OAUTH_ENV


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    monkeypatch.setattr(cloud_inject, "ENV_FILE", str(tmp_path / "none.env"))
    for k in cloud_inject.REQUIRED_ENV + AUTH_ENV:
        monkeypatch.delenv(k, raising=False)
    return monkeypatch


def test_env_config_reports_all_missing(clean_env):
    with pytest.raises(SystemExit) as e:
        cloud_inject.env_config()
    for k in cloud_inject.REQUIRED_ENV + AUTH_ENV:
        assert k in str(e.value)


def test_access_token_prefers_api_key(clean_env):
    for k, v in {"PROJECT_UID": "app:p", "DEVICE_UID": "dev:1", "NOTEHUB_API_KEY": "pat", "NOTEHUB_CLIENT_ID": "cid", "NOTEHUB_CLIENT_SECRET": "cs"}.items():
        clean_env.setenv(k, v)
    s = FakeSession([])
    assert cloud_inject.access_token(cloud_inject.env_config(), session=s) == "pat"
    assert s.calls == []


def test_access_token_falls_back_to_oauth(clean_env):
    for k, v in {"PROJECT_UID": "app:p", "DEVICE_UID": "dev:1", "NOTEHUB_CLIENT_ID": "cid", "NOTEHUB_CLIENT_SECRET": "cs"}.items():
        clean_env.setenv(k, v)
    s = FakeSession([FakeResponse(200, {"access_token": "tok123"})])
    assert cloud_inject.access_token(cloud_inject.env_config(), session=s) == "tok123"


def test_load_env_file_fills_blanks_only(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text('# comment\nPROJECT_UID="app:abc"\nDEVICE_UID=dev:from-file\nNOTEHUB_CLIENT_ID=\n')
    monkeypatch.delenv("PROJECT_UID", raising=False)
    monkeypatch.delenv("NOTEHUB_CLIENT_ID", raising=False)
    monkeypatch.setenv("DEVICE_UID", "dev:from-shell")
    cloud_inject.load_env_file(str(env))
    assert os.environ["PROJECT_UID"] == "app:abc"
    assert os.environ["DEVICE_UID"] == "dev:from-shell"
    assert "NOTEHUB_CLIENT_ID" not in os.environ


# --- send_demo ---------------------------------------------------------------

def test_send_telemetry_adds_note_then_forces_sync():
    card = FakeNotecard({"note.add": {"total": 1}})
    body = build_telemetry(seq=7)
    send_telemetry(NotecardLink(card), body)
    assert card.requests[0] == {"req": "note.add", "file": "telemetry.qo", "body": body, "sync": True}
    assert card.requests[1] == {"req": "hub.sync"}
    assert body["seq"] == 7 and body["source"] == "send_demo"


# --- mqtt_watch --------------------------------------------------------------

def test_format_notehub_event():
    event = {"event": "e1", "device": "dev:868531063312800", "file": "telemetry.qo",
             "body": {"seq": 1, "battery_v": 12.3}, "when": 1700000000}
    out = mqtt_watch.format_message("robot/dev:868531063312800/telemetry.qo", json.dumps(event).encode())
    assert "telemetry.qo" in out and "dev:868531063312800" in out and '"battery_v": 12.3' in out


def test_format_non_json_payload_falls_back_to_raw():
    out = mqtt_watch.format_message("t", b"\xffnot json")
    assert "t" in out and "not json" in out
