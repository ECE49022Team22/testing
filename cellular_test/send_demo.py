"""Uplink test: add one note to telemetry.qo and force a Notehub sync."""

import argparse
import json
import time

from notecard_link import NotecardLink, open_card

TELEMETRY_FILE = "telemetry.qo"


def build_telemetry(seq=0):
    # Fake values: this is a link test, not real robot telemetry.
    return {"source": "send_demo", "seq": seq, "pi_time": int(time.time()), "battery_v": 12.3}


def send_telemetry(link, body):
    rsp = link.send_note(TELEMETRY_FILE, body, sync=True)
    link.sync()
    return rsp


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seq", type=int, default=0)
    ap.add_argument("--wait", type=float, default=60.0, help="seconds to watch hub.sync.status (0 = don't)")
    args = ap.parse_args()

    link = NotecardLink(open_card())
    body = build_telemetry(args.seq)
    print(f"note.add {TELEMETRY_FILE}: {json.dumps(body)} -> {json.dumps(send_telemetry(link, body))}")

    deadline = time.time() + args.wait
    while time.time() < deadline:
        st = link.request({"req": "hub.sync.status"})
        print(f"hub.sync.status: {json.dumps(st)}")
        if st.get("completed") and not st.get("sync"):
            break
        time.sleep(3)


if __name__ == "__main__":
    main()
