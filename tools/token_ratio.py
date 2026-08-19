#!/usr/bin/env python3
"""Measure chars-per-token per material type with countTokens. FREE endpoint, no spend.

WHY NOT JUST DIVIDE BY 3.5
The 1,048,576-token ceiling is hard, and a batch is irreversible spend at submit. An
estimate that is 40% low does not produce a smaller bill — it produces a 400 INVALID_ARGUMENT
after the corpus has already been assembled, or worse, a silently truncated review. Cyrillic
runs closer to 2 chars/token than English's ~4, and this corpus is mixed EN/RU legal text
plus OCR noise plus PDF form templates, each with its own ratio. So measure each, on a real
sample, against the tokenizer that will actually bill.

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


def count_tokens(text: str, model: str, key: str) -> tuple[int, int | str]:
    payload = {"contents": [{"role": "user", "parts": [{"text": text}]}]}
    req = urllib.request.Request(
        f"{API}/models/{model}:countTokens",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.status, json.loads(r.read().decode()).get("totalTokens")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]
    except Exception as e:                                     # noqa: BLE001
        return 0, f"{type(e).__name__}: {str(e)[:200]}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="append", required=True,
                    metavar="LABEL=PATH", help="repeatable")
    ap.add_argument("--model", default="gemini-3.7-flash")
    ap.add_argument("--max-chars", type=int, default=250_000,
                    help="per sample; countTokens is free but the request still has a size")
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    key = os.environ["GEMINI_API_KEY"]                          # never printed
    rows = []
    for spec in a.sample:
        label, _, path = spec.partition("=")
        p = pathlib.Path(path)
        if not p.exists():
            print(f"  MISSING {label}: {path}")
            continue
        if p.suffix.lower() == ".pdf":
            import fitz
            with fitz.open(p) as doc:
                text = "".join(doc.load_page(i).get_text("text")
                               for i in range(min(doc.page_count, 60)))
        else:
            text = p.read_text(encoding="utf-8", errors="replace")
        text = text[: a.max_chars]
        st, tok = count_tokens(text, a.model, key)
        if st != 200 or not isinstance(tok, int):
            print(f"  {label:22} HTTP {st}  {tok}")
            continue
        ratio = len(text) / tok if tok else 0
        rows.append({"label": label, "path": str(p), "chars": len(text),
                     "tokens": tok, "chars_per_token": round(ratio, 3)})
        print(f"  {label:22} {len(text):9,} ch -> {tok:8,} tok   "
              f"{ratio:5.2f} ch/tok")

    if rows:
        worst = min(r["chars_per_token"] for r in rows)
        print(f"\n  WORST (densest) ratio: {worst:.2f} ch/tok — plan the ceiling on THIS, "
              f"not on the average. An average that overshoots the ceiling is a 400 after "
              f"the corpus is already built.")
    if a.out:
        o = pathlib.Path(a.out)
        o.parent.mkdir(parents=True, exist_ok=True)
        o.write_text(json.dumps({"model": a.model, "samples": rows},
                                ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  -> {o}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
