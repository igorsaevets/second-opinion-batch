#!/usr/bin/env python3
"""Poll a batch until it leaves in_progress, then print the result line.

Separate from heavy_batch.py so the submit path stays free of loops: a retry
loop next to a billable POST is how an accidental double-charge happens.
This only ever issues GETs.
"""
from __future__ import annotations

import argparse
import pathlib
import random
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="smoke")
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--rundir", required=True)
    ap.add_argument("--max-min", type=int, default=45)
    a = ap.parse_args()

    deadline = time.monotonic() + a.max_min * 60
    n = 0
    while time.monotonic() < deadline:
        n += 1
        p = subprocess.run(
            [sys.executable, str(HERE / "heavy_batch.py"), "--mode", "poll",
             "--tag", a.tag, "--corpus", a.corpus, "--rundir", a.rundir],
            capture_output=True, text=True,
        )
        line = (p.stdout or p.stderr).strip().splitlines()
        print(f"[{n}] {time.strftime('%H:%M:%S')} exit={p.returncode} "
              f"{line[0] if line else ''}", flush=True)
        if p.returncode != 3:
            for extra in line[1:]:
                print(f"    {extra}", flush=True)
            return p.returncode
        # Vary the interval rather than running a metronome.
        time.sleep(random.uniform(20, 40))

    print("TIMEOUT: still in_progress")
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
