"""Check the robot's link to the live web app, without the robot. Runs on the Pi (over the hotspot) or a laptop.

    python3 nav/app_check.py check     read-only: DNS, direct and NAT64 connections, the token, what the inbox returns
    python3 nav/app_check.py pretend   be the robot, with the real delivery.py + app_link.py and no hardware: order in
                                       the app and watch the whole delivery happen (each leg "drives" in --leg-s)

Both read the token from --token-file (default ~/.config/cosmo_robot.env, ROBOT_API_TOKEN=...).
Only run `pretend` while the real robot's program is stopped: the app can't tell them apart.
"""
import argparse
import math
import socket
import time

import app_link
import delivery as dlv


def check(a, token):
    link = app_link.AppLink(dlv.Delivery(), a.url, token)
    host, port = link.conn_args
    print(f"app: {a.url}")
    ip4 = ip6 = []
    try:
        ip4 = sorted({r[4][0] for r in socket.getaddrinfo(host, port, socket.AF_INET)})
        print(f"  DNS IPv4: {', '.join(ip4)}")
    except OSError as e:
        print(f"  DNS IPv4: none ({e})")
    try:
        ip6 = sorted({r[4][0] for r in socket.getaddrinfo(host, port, socket.AF_INET6)})
        print(f"  DNS IPv6: {', '.join(ip6)}" + ("  (DNS64: the carrier makes these up for an IPv4-only site)"
                                                  if any(x.startswith("64:ff9b:") for x in ip6) else ""))
    except OSError:
        print("  DNS IPv6: none (normal: *.vercel.app is IPv4-only)")
    for name, addr in [("IPv4", ip4[0] if ip4 else None), ("IPv6", ip6[0] if ip6 else None),
                       ("NAT64", app_link.nat64(ip4[0]) if ip4 else None)]:
        if addr:
            try:
                socket.create_connection((addr, port), 5).close()
                print(f"  connect over {name} ({addr}): ok")
            except OSError as e:
                print(f"  connect over {name} ({addr}): no ({e})")
    t0 = time.monotonic()
    try:
        inbox = link.request("GET", "/api/robot/inbox")
    except Exception as e:
        print(f"\nFAILED: GET /api/robot/inbox: {e}")
        return 1
    ms = (time.monotonic() - t0) * 1000
    server = dlv.parse_time(inbox.get("now"))
    print(f"\nGET /api/robot/inbox: ok in {ms:.0f} ms (token accepted)")
    print(f"  app commit {inbox.get('commit')}, asks for a poll every {inbox.get('pollSeconds')} s")
    print(f"  app clock {inbox.get('now')!r}" + (f" ({server - time.time():+.1f} s from this machine's clock)" if server else
                                                  "  WARNING: can't read this time format, so stale commands can't be spotted"))
    cmds = inbox.get("commands") or []
    print(f"  {len(cmds)} command(s) waiting for the robot" + "".join(
        f"\n    {c.get('type')} {c.get('id')} issued {c.get('issuedAt')}" for c in cmds))
    print("\nLink OK.")
    return 0


def along(points, f):
    """The point a fraction f (0..1) of the way along a [(lat, lon), ...] line."""
    k = math.cos(math.radians(points[0][0]))
    seg = [math.hypot(b[0] - a[0], (b[1] - a[1]) * k) for a, b in zip(points, points[1:])]
    togo = f * sum(seg)
    for p, q, s in zip(points, points[1:], seg):
        if togo <= s and s > 0:
            t = togo / s
            return round(p[0] + t * (q[0] - p[0]), 7), round(p[1] + t * (q[1] - p[1]), 7)
        togo -= s
    return points[-1]


def pretend(a, token):
    dm = dlv.Delivery()
    dm.pos = tuple(float(x) for x in a.start.split(","))
    link = app_link.AppLink(dm, a.url, token)
    link.start()
    print(f"pretending to be the robot at {dm.pos} for {a.url}. Order in the app; Ctrl-C to stop.")
    leg_t0, last = None, None
    try:
        while True:
            with dm.lock:
                leg = dm.current_leg()
                if leg and leg_t0 is None:
                    leg_t0 = time.monotonic()
                if leg:
                    f = min(1.0, (time.monotonic() - leg_t0) / a.leg_s)
                    dm.pos = along(leg[1], f)
                    if f >= 1.0:
                        dm.arrived_at_stop()
                        leg_t0 = None
                shown = (dm.state, dm.lid.state, link.status)
            if shown != last:
                print(f"{time.strftime('%H:%M:%S')}  {shown[0]:21s} lid {shown[1]:8s} link {shown[2]}", flush=True)
                last = shown
            time.sleep(0.5)
    except KeyboardInterrupt:
        link.stop()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", choices=("check", "pretend"))
    ap.add_argument("--url", default=app_link.DEFAULT_URL)
    ap.add_argument("--token-file", default="~/.config/cosmo_robot.env")
    ap.add_argument("--leg-s", type=float, default=20.0, help="pretend: seconds to 'drive' each leg")
    ap.add_argument("--start", default="40.428589,-86.911542", help="pretend: starting lat,lon (BHEE courtyard)")
    a = ap.parse_args()
    token = app_link.load_token(a.token_file)
    return check(a, token) if a.what == "check" else pretend(a, token)


if __name__ == "__main__":
    raise SystemExit(main())
