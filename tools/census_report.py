#!/usr/bin/env python3
"""Summarise a pdf_census.json: where the characters actually are.

A total character count decides nothing. What decides the corpus is WHICH files carry the
mass, because the 1,048,576-token ceiling forces a choice and the choice should be made on
evidence rather than on which directory sounds important.

Read-only. No network, no spend.
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib

CH_PER_TOK = 3.5   # rough; countTokens is authoritative and free — measure before spending


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--census", required=True)
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--group-depth", type=int, default=7,
                    help="path components to keep when grouping")
    a = ap.parse_args()

    data = json.loads(pathlib.Path(a.census).read_text(encoding="utf-8"))
    files = data["files"]

    by_group: dict[str, dict] = collections.defaultdict(
        lambda: {"files": 0, "chars": 0, "text": 0, "scan": 0, "err": 0})
    for f in files:
        parts = pathlib.Path(f["path"]).parts
        g = "\\".join(parts[:a.group_depth])
        b = by_group[g]
        b["files"] += 1
        b["chars"] += f.get("chars", 0)
        if f["kind"] == "TEXT":
            b["text"] += 1
        elif f["kind"] == "SCAN":
            b["scan"] += 1
        elif f["kind"] == "ERROR":
            b["err"] += 1

    print("=== BY GROUP ===")
    tot = 0
    for g, b in sorted(by_group.items(), key=lambda x: -x[1]["chars"]):
        tot += b["chars"]
        print(f"{b['chars']:12,}  ~{b['chars']/CH_PER_TOK/1000:7.0f}K tok  "
              f"{b['files']:4} f (T{b['text']}/S{b['scan']}/E{b['err']})  {g}")
    print(f"{tot:12,}  ~{tot/CH_PER_TOK/1000:7.0f}K tok  TOTAL")

    print(f"\n=== TOP {a.top} FILES ===")
    for f in sorted(files, key=lambda x: -x.get("chars", 0))[:a.top]:
        p = pathlib.Path(f["path"])
        print(f"{f.get('chars',0):10,}  {f.get('pages','-'):>4}p  {f['kind']:5}  "
              f"{p.parent.name[:28]:28}  {p.name[:60]}")

    print("\n=== SCANS WITHOUT OCR (the model must be TOLD these exist) ===")
    n = 0
    for f in files:
        if f["kind"] == "SCAN" and not f.get("ocr_sidecar"):
            n += 1
            p = pathlib.Path(f["path"])
            print(f"  {f.get('pages','-'):>4}p  {f.get('chars',0):>6} ch  "
                  f"{p.parent.name[:26]:26}  {p.name[:64]}")
    if not n:
        print("  none")

    errs = [f for f in files if f["kind"] == "ERROR"]
    if errs:
        print("\n=== ERRORS ===")
        for f in errs:
            print(f"  {pathlib.Path(f['path']).name[:70]}  {f.get('error')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
