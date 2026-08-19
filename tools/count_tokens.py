#!/usr/bin/env python3
"""Count tokens of corpus files against the model that will bill for them. FREE, no spend.

THIS IS THE PRE-SUBMIT GATE.
`inputTokenLimit` for gemini-3.7-flash is 1,048,576 (measured 2026-08-19 off the models
endpoint, not copied from prose). A batch is irreversible spend at submit; an over-ceiling
payload does not fail cheaply once N items are already in flight, and a chars/3.5 estimate
was measured wrong by up to 1.9x on this very corpus — exhibit tables run 2.35 ch/tok while
the Russian petition runs 4.47. So the number that gates the run is a counted one.

Counts in chunks and sums. Chunk boundaries can shift a token or two per split; that is
noise against a ceiling check, and the alternative (a single call) fails outright above the
limit, which is the exact case this exists to detect.

Reads GEMINI_API_KEY from the environment. NEVER prints or logs the key.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import urllib.error
import urllib.request

API = "https://generativelanguage.googleapis.com/v1beta"


def count(text: str, model: str, key: str) -> int:
    req = urllib.request.Request(
        f"{API}/models/{model}:countTokens",
        data=json.dumps({"contents": [{"role": "user",
                                       "parts": [{"text": text}]}]}).encode(),
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return int(json.loads(r.read().decode())["totalTokens"])
    except urllib.error.HTTPError as e:
        raise SystemExit(f"countTokens HTTP {e.code}: {e.read().decode()[:400]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", action="append", required=True)
    ap.add_argument("--model", default="gemini-3.7-flash")
    ap.add_argument("--chunk", type=int, default=400_000, help="chars per countTokens call")
    ap.add_argument("--ceiling", type=int, default=1_048_576)
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    key = os.environ["GEMINI_API_KEY"]                          # never printed
    rows, total = [], 0
    for f in a.file:
        p = pathlib.Path(f)
        if not p.exists():
            print(f"  MISSING {f}")
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        n = 0
        for i in range(0, len(text), a.chunk):
            n += count(text[i:i + a.chunk], a.model, key)
        total += n
        ratio = len(text) / n if n else 0
        rows.append({"file": p.name, "chars": len(text), "tokens": n,
                     "chars_per_token": round(ratio, 2)})
        print(f"  {p.name:24} {len(text):10,} ch  {n:9,} tok  {ratio:5.2f} ch/tok  "
              f"{n / a.ceiling * 100:5.1f}% of ceiling")

    print(f"\n  {'TOTAL':24} {sum(r['chars'] for r in rows):10,} ch  {total:9,} tok  "
          f"{total / a.ceiling * 100:5.1f}% of ceiling ({a.ceiling:,})")
    if total > a.ceiling:
        print(f"  OVER CEILING by {total - a.ceiling:,} tokens — this payload would 400. "
              f"Drop a tier; do not truncate a document mid-way.")
    if a.out:
        o = pathlib.Path(a.out)
        o.parent.mkdir(parents=True, exist_ok=True)
        o.write_text(json.dumps({"model": a.model, "ceiling": a.ceiling,
                                 "total_tokens": total, "files": rows},
                                ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  -> {o}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
