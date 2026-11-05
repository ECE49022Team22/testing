#!/usr/bin/env python3
"""Map how the skid-steer chassis actually turns: a series of fixed-ratio arcs, each driven forward
and then reversed back along itself so the robot ends near where it started (no repositioning).

  turnmap.py [--outer 30] [--ratios 1 0.75 0.5 0.25 0 -0.25 -0.5 -1] [--leg-s 3] [--side right]

The outer wheel holds --outer RPM; the inner wheel runs ratio x outer (negative = backwards, -1 = spin
in place). Logs every control tick (wheel speeds, duties, gyro) and every LiDAR scan to
~/motor_cal/turnmap_<time>.pkl for offline analysis (scan matching gives the true motion, so wheel
slip can be measured). Same safety as robot_drive.py: LiDAR guard, time limit, STOP file, stall fault.
"""
import argparse
import math
import os
import pickle
import sys
import time

sys.path.insert(0, os.path.expanduser("~/motor_cal"))
import robot_drive as rd                          # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--outer", type=float, default=30.0, help="outer wheel RPM")
    ap.add_argument("--ratios", type=float, nargs="+", default=[1, 0.75, 0.5, 0.25, 0, -0.25, -0.5, -1])
    ap.add_argument("--leg-s", type=float, default=3.0, help="seconds at speed per leg (plus ramps)")
    ap.add_argument("--side", choices=("left", "right"), default="right")
    ap.add_argument("--stop-dist", type=int, default=500)
    ap.add_argument("--max-s", type=float, default=150)
    ap.add_argument("--set", nargs="*", default=[], metavar="CMD",
                    help='gain commands for both motors for this series, e.g. --set "kf 0.45" "ks 3.5" "kp 0.3"; '
                         "the previous gains are restored at the end")
    ap.add_argument("--label", default="", help="name for this series in the log")
    a = ap.parse_args()

    lid, imu, mcu, guard = rd.start(a)
    before = {p: mcu.gains(p) for p in ("", "m2 ")}
    for c in a.set:
        for p in ("", "m2 "):
            print(f"  {p or 'm1 '}{c} -> {mcu.command(p + c)}", flush=True)
    scans = []
    # the Lidar thread keeps only the newest scan: tap() copies each new one out on every control tick
    last_t = [0.0]

    def tap():
        if lid.t != last_t[0] and lid.scan is not None:
            last_t[0] = lid.t
            scans.append((lid.t, lid.scan))

    ticks, results = [], []
    t_start = time.monotonic()
    stop_reason = None
    try:
        for q in a.ratios:
            outer, inner = a.outer, a.outer * q
            if inner == 0:
                inner = 0.05                      # exactly 0 makes the firmware switch the motor off
            l, r = (inner, outer) if a.side == "left" else (outer, inner)
            for leg, sign in (("fwd", 1), ("back", -1)):
                imu_yaw0 = imu.yaw
                total = a.leg_s + 1.6
                tag = f"q={q:+.2f} {leg}"

                def step(t, sign=sign, l=l, r=r, total=total, tag=tag):
                    tap()
                    k = rd.ramp(t, total, 1.0)
                    if k is None:
                        return None
                    row = mcu.row
                    (ml, mr), (cl, cr) = mcu.wheels()
                    ticks.append(dict(t=time.monotonic() - t_start, test=tag, q=q, leg=leg, cmd_l=sign * l * k,
                                      cmd_r=sign * r * k, ml=ml, mr=mr, cl=cl, cr=cr,
                                      duty_l=row[7] * rd.LEFT_SIGN, duty_r=row[2] * rd.RIGHT_SIGN,
                                      gz=math.degrees(imu.gz), yaw=math.degrees(imu.yaw), flags=mcu.flags.strip()))
                    return sign * l * k, sign * r * k

                why = rd.run_loop(mcu, guard, step)
                pause_end = time.monotonic() + 1.0
                while time.monotonic() < pause_end:
                    tap(); time.sleep(0.02)
                seg = [x for x in ticks if x["test"] == tag]
                steady = [x for x in seg if 1.2 < x["t"] - seg[0]["t"] < a.leg_s + 0.8] or seg
                n = max(1, len(steady))
                res = dict(test=tag, q=q, leg=leg,
                           yaw_rate=sum(x["gz"] for x in steady) / n,
                           ml=sum(x["ml"] for x in steady) / n, mr=sum(x["mr"] for x in steady) / n,
                           duty_l=sum(x["duty_l"] for x in steady) / n, duty_r=sum(x["duty_r"] for x in steady) / n,
                           turned=math.degrees(imu.yaw - imu_yaw0), stopped=why)
                v = (res["ml"] + res["mr"]) / 2 / 60 * rd.WHEEL_C
                dv = (res["mr"] - res["ml"]) / 60 * rd.WHEEL_C
                w = math.radians(res["yaw_rate"])
                res["track_eff"] = dv / w if abs(w) > 1e-3 else float("nan")
                res["radius"] = v / w if abs(w) > 1e-3 else float("inf")
                results.append(res)
                print(f"{tag:12s} wheels L {res['ml']:+6.1f} R {res['mr']:+6.1f} RPM  duty L {res['duty_l']:+5.0f}% "
                      f"R {res['duty_r']:+5.0f}%  yaw {res['yaw_rate']:+6.1f} deg/s (turned {res['turned']:+5.0f})  "
                      f"eff track {res['track_eff'] * 100:5.0f} cm  radius {res['radius']:+6.2f} m"
                      + (f"  STOPPED: {why}" if why else ""), flush=True)
                if why:
                    stop_reason = why
                    break
            if stop_reason:
                break
    finally:
        mcu.stop()
        for p, g in before.items():               # put the gains back as they were
            for k, v in g.items():
                mcu.command(f"{p}{k} {v:g}")
        path = os.path.expanduser(f"~/motor_cal/turnmap_{a.label or 'run'}_{time.strftime('%H%M%S')}.pkl")
        with open(path, "wb") as f:
            pickle.dump(dict(args=vars(a), ticks=ticks, results=results, scans=scans, gains_before=before), f)
        print(f"log: {path} ({len(ticks)} ticks, {len(scans)} scans)", flush=True)
        imu.close(); mcu.close()


if __name__ == "__main__":
    main()
