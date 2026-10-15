#!/usr/bin/env python3
"""Compare runs side by side on the headline metrics (first run = reference).

  python3 compare.py results/<baseline> results/<pinned> [results/<more> ...]
"""
import json
import os
import sys

from summarize import HEADLINE


def load(d):
    with open(os.path.join(d, "summary.json")) as f:
        return json.load(f)


def cell(ref, val):
    if val is None:
        return "-"
    if ref in (None, 0) or ref is val:
        return f"{val:.2f}"
    return f"{val:.2f} ({100 * (val - ref) / ref:+.0f}%)"


def main():
    runs = [load(d) for d in sys.argv[1:]]
    if len(runs) < 2:
        sys.exit(__doc__)
    rows = []
    for w, m in HEADLINE:
        for stat in ("p50", "p99", "max"):
            vals = [r["workers"].get(w, {}).get("metrics", {}).get(m, {}).get(stat) for r in runs]
            rows.append((f"{w}.{m} {stat}", vals))
        over = [r["workers"].get(w, {}).get("metrics", {}).get(m, {}).get("over_budget_pct") for r in runs]
        if any(v is not None for v in over):
            rows.append((f"{w}.{m} % over budget", over))
    for k in sorted({k for r in runs for k in r["rates"]}):
        rows.append((k, [r["rates"].get(k) for r in runs]))
    for stat in ("p99", "max"):
        vals = [max((c[stat] for c in r.get("jitter", {}).values()), default=None) for r in runs]
        rows.append((f"sched latency worst core {stat} (µs)", [float(v) if v is not None else None for v in vals]))

    print("| metric | " + " | ".join(r["run"] for r in runs) + " |")
    print("|---|" + "---:|" * len(runs))
    for name, vals in rows:
        print(f"| {name} | " + " | ".join(cell(vals[0], v) if i else cell(None, v)
                                         for i, v in enumerate(vals)) + " |")
    print("\n(lower is better for latencies; % is change vs the first run)")


if __name__ == "__main__":
    main()
