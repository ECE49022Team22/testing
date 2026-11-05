import re, time, serial
TEL = re.compile(r"tgt=(-?[\d.]+) meas=(-?[\d.]+) duty=(-?[\d.]+)% cap=(-?[\d.]+)% cnt=(-?\d+) "
                 r"tgt2=(-?[\d.]+) meas2=(-?[\d.]+) duty2=(-?[\d.]+)% cap2=(-?[\d.]+)% cnt2=(-?\d+)(.*)")
LEFT_SIGN, RIGHT_SIGN = -1, 1           # left = motor 1 (mounted reversed), right = motor 2
s = serial.Serial("/dev/ttyUSB0", 115200, timeout=0.2)
def run(cmd, sec):
    s.write((cmd + "\n").encode()); rows = []; end = time.time() + sec
    while time.time() < end:
        m = TEL.match(s.readline().decode(errors="replace").strip())
        if m: rows.append([float(x) for x in m.groups()[:10]] + [m.group(11)])
    return rows
def score(meas, tgt, prev):
    step = tgt - prev
    peak = max(meas) if step > 0 else min(meas)
    over = 0.0 if step == 0 else max(0.0, (peak - tgt) / abs(step) * 100 * (1 if step > 0 else -1))
    late = meas[len(meas) * 2 // 3:]
    avg = sum(late) / len(late)
    sd = (sum((x - avg) ** 2 for x in late) / len(late)) ** 0.5
    return over, avg - tgt, sd
try:
    s.write(b"reset\nrate 50\n"); time.sleep(0.3); s.reset_input_buffer()
    prev = (0, 0)
    for name, l, r in (("forward 60", 60, 60), ("forward 120", 120, 120), ("forward 160", 160, 160), ("stop", 0, 0),
                       ("back 60", -60, -60), ("spin left 40", -40, 40), ("spin right 40", 40, -40), ("stop", 0, 0)):
        m1, m2 = l * LEFT_SIGN + 0.0, r * RIGHT_SIGN + 0.0
        rows = run(f"d {m1:g} {m2:g}", 2.5)
        flags = rows[-1][10].strip()
        o1, e1, j1 = score([x[1] for x in rows], m1, prev[0]); o2, e2, j2 = score([x[6] for x in rows], m2, prev[1])
        L, R = rows[-1][1] * LEFT_SIGN, rows[-1][6] * RIGHT_SIGN
        print(f"{name:14s} wheels L {L:+6.1f} R {R:+6.1f} RPM | m1 over {o1:4.1f}% err {e1:+5.1f} jit {j1:3.1f} duty {rows[-1][2]:+5.1f}% | "
              f"m2 over {o2:4.1f}% err {e2:+5.1f} jit {j2:3.1f} duty {rows[-1][7]:+5.1f}% {flags if 'FAULT' in flags or 'stall' in flags else ''}", flush=True)
        prev = (m1, m2)
    print("done", flush=True)
finally:
    s.write(b"stop\n"); time.sleep(0.1); s.write(b"rate 10\n"); time.sleep(0.1); s.close()
