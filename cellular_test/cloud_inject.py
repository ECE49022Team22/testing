"""Cloud side of the downlink test: add a note to the device's commands.qi via the Notehub REST API.

Env (or .env): PROJECT_UID, DEVICE_UID, and either NOTEHUB_API_KEY (personal access token,
Notehub user menu -> API Access) or the deprecated NOTEHUB_CLIENT_ID + NOTEHUB_CLIENT_SECRET.
Usage: python cloud_inject.py '{"id":"abc","type":"navigate","body":{"lat":40.42,"lon":-86.91}}'
"""

import argparse
import json
import os
import sys
import uuid

import requests

API = "https://api.notefile.net"
REQUIRED_ENV = ("PROJECT_UID", "DEVICE_UID")
OAUTH_ENV = ("NOTEHUB_CLIENT_ID", "NOTEHUB_CLIENT_SECRET")
ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


def load_env_file(path=None):
    """Fill os.environ from KEY=VALUE lines in .env; real env vars win, blank values are skipped."""
    path = path or ENV_FILE
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.strip().strip("\"'")
            if value:
                os.environ.setdefault(key.strip(), value)


def env_config():
    load_env_file()
    missing = [k for k in REQUIRED_ENV if not os.environ.get(k)]
    has_oauth = all(os.environ.get(k) for k in OAUTH_ENV)
    if not os.environ.get("NOTEHUB_API_KEY") and not has_oauth:
        missing.append("NOTEHUB_API_KEY (or NOTEHUB_CLIENT_ID + NOTEHUB_CLIENT_SECRET)")
    if missing:
        raise SystemExit(f"missing env vars: {', '.join(missing)}")
    keys = REQUIRED_ENV + ("NOTEHUB_API_KEY",) + OAUTH_ENV
    return {k: os.environ[k] for k in keys if os.environ.get(k)}


def access_token(cfg, session=requests):
    """Personal access token if set, else trade the OAuth client credentials for a bearer token."""
    if cfg.get("NOTEHUB_API_KEY"):
        return cfg["NOTEHUB_API_KEY"]
    return get_token(cfg["NOTEHUB_CLIENT_ID"], cfg["NOTEHUB_CLIENT_SECRET"], session=session)


def get_token(client_id, client_secret, session=requests):
    rsp = session.post(
        f"{API}/oauth2/token",
        data={"grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret},
        timeout=15,
    )
    rsp.raise_for_status()
    return rsp.json()["access_token"]


def inject_note(token, project_uid, device_uid, body, file="commands.qi", session=requests):
    rsp = session.post(
        f"{API}/v1/projects/{project_uid}/devices/{device_uid}/notes/{file}",
        headers={"Authorization": f"Bearer {token}"},
        json={"body": body},
        timeout=15,
    )
    rsp.raise_for_status()
    return rsp


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", nargs="?", help="JSON command body (default: a ping)")
    args = ap.parse_args()

    cmd = json.loads(args.command) if args.command else {"id": uuid.uuid4().hex[:8], "type": "ping"}
    cfg = env_config()
    token = access_token(cfg)
    rsp = inject_note(token, cfg["PROJECT_UID"], cfg["DEVICE_UID"], cmd)
    print(f"POST commands.qi -> HTTP {rsp.status_code} {rsp.text.strip()}")
    print(f"sent: {json.dumps(cmd)}")


if __name__ == "__main__":
    try:
        main()
    except requests.HTTPError as e:
        sys.exit(f"HTTP error: {e} {e.response.text if e.response is not None else ''}")
