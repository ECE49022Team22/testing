"""Thin, transport-agnostic client for a Blues Notecard (bring-up test only).

The Notecard is NOT a modem: we exchange line-delimited JSON requests with it
over Serial (USB/UART) or I2C, and it syncs Notes with Notehub on its own.

Transport swap: everything goes through open_card(). To move from USB serial
to I2C, change the single line in open_card() from open_serial() to open_i2c().
"""

import os
import time

DEFAULT_SERIAL_PORT = os.environ.get("NOTECARD_PORT", "/dev/ttyACM0")
DEFAULT_SERIAL_BAUD = 9600
DEFAULT_I2C_BUS = "/dev/i2c-1"
NOTECARD_I2C_ADDR = 0x17


class NotecardError(RuntimeError):
    """The Notecard answered with an "err" field."""


def open_serial(port=DEFAULT_SERIAL_PORT, baud=DEFAULT_SERIAL_BAUD, debug=False):
    import notecard
    import serial

    return notecard.OpenSerial(serial.Serial(port, baud, timeout=10), debug=debug)


def open_i2c(bus=DEFAULT_I2C_BUS, address=NOTECARD_I2C_ADDR, debug=False):
    import notecard
    from periphery import I2C

    # max_transfer=0 lets note-python use its default chunk size.
    return notecard.OpenI2C(I2C(bus), address, 0, debug=debug)


def open_card():
    """The one place that picks the physical interface."""
    return open_i2c()  # <- change to: return open_serial() for USB


class NotecardLink:
    """Wraps any object with note-python's Transaction(dict) -> dict interface."""

    def __init__(self, card):
        self.card = card

    def request(self, req):
        rsp = self.card.Transaction(req)
        if "err" in rsp:
            raise NotecardError(f"{req.get('req')}: {rsp['err']}")
        return rsp

    def send_note(self, file, body, sync=True):
        if not isinstance(body, dict):
            raise TypeError("note body must be a dict")
        return self.request({"req": "note.add", "file": file, "body": body, "sync": sync})

    def receive_notes(self, file):
        """Drain pending inbound notes from `file`; returns their bodies, oldest first."""
        try:
            rsp = self.request({"req": "note.changes", "file": file, "delete": True})
        except NotecardError as e:
            if "{note-noexist}" in str(e):
                return []  # nothing has ever been sent to this Notefile
            raise
        notes = sorted((rsp.get("notes") or {}).values(), key=lambda n: n.get("time", 0))
        return [n.get("body", {}) for n in notes]

    def sync(self):
        return self.request({"req": "hub.sync"})

    def enable_immediate_sync(self):
        """Keep a Notehub session open and have Notehub push inbound notes right away.

        Without sync:true, notes added in Notehub wait for the card's periodic inbound
        check (minutes). With it, delivery is ~1.5-3 s at a small power cost. The card
        stores this setting, so re-applying it is harmless.
        """
        return self.request({"req": "hub.set", "mode": "continuous", "sync": True})

    def hub_status(self):
        return self.request({"req": "hub.status"})

    def wireless_status(self):
        return self.request({"req": "card.wireless"})

    def now(self):
        """Epoch seconds from the Notecard's network clock; falls back to the Pi clock
        if the card has no time yet (the Pi may have no NTP when it's on cellular only)."""
        try:
            t = self.request({"req": "card.time"}).get("time")
        except NotecardError:
            t = None
        return t if t else time.time()

    def version(self):
        return self.request({"req": "card.version"})


if __name__ == "__main__":
    import json

    link = NotecardLink(open_card())
    for name in ("version", "hub_status", "wireless_status"):
        print(f"{name}: {json.dumps(getattr(link, name)())}")
