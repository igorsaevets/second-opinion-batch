#!/usr/bin/env python3
"""Did the model actually READ the middle of the long prompt, or only its ends?

A long-context answer that sounds thorough is not evidence that the middle was
read — "lost in the middle" is a documented attention failure, and a fluent
summary of the head and tail is indistinguishable from a real full read from
the outside. So plant ONE unambiguous, legally material contradiction at the
50% depth mark and ask the ordinary contradictions question. If the planted
flaw comes back, the middle was read. If it does not, every negative finding
from that lens ("no contradictions here") is worthless, because the instrument
was never shown to reach that far.

Raised independently by two reviewers on 2026-08-17: "you have no canary flaw
injected into the text to prove the LLM actually read it."

The canary is inserted into a COPY. The redacted corpus on disk is never edited.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from heavy_batch import OR_BASE, SYSTEM, build_corpus, get, post  # noqa: E402

# Chosen to be (a) unambiguous, (b) legally material — it breaks the continuous
# physical presence the record asserts elsewhere and would change the INA 245
# analysis — and (c) impossible to infer from the head or the tail. It contradicts
# a sentence that lives in a DIFFERENT file, so finding it requires holding two
# distant regions at once, not just reading one paragraph.
CANARY = (
    "\n\nFor completeness of the chronology, the applicant records the following: "
    "the applicant departed the United States on 14 March 2023, travelled abroad, "
    "and was re-admitted at Los Angeles International Airport on 2 May 2023. "
    "No application for advance parole was filed before that departure.\n\n"
)

CANARY_MARKERS = ("14 March 2023", "2 May 2023", "departed", "advance parole")

LENS = (
    "REVIEW LENS — contradictions\n\n"
    "INTERNAL CONTRADICTIONS across the documents. Find dates, numbers, titles and "
    "factual claims that conflict BETWEEN documents. An officer reads them together. "
    "Quote BOTH sides of each conflict and name the two files.\n\n"
    "Return ONLY JSON: {\"contradictions\": [{\"claim_a\": \"...\", \"file_a\": \"...\", "
    "\"claim_b\": \"...\", \"file_b\": \"...\", \"why_it_matters\": \"...\"}]}"
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--rundir", required=True)
    ap.add_argument("--model", default="google/gemini-3.7-flash:batch")
    ap.add_argument("--mode", choices=["submit", "check"], required=True)
    # R07: with reference guides appended, the midpoint of the PAYLOAD falls
    # inside a guide, and spiking a guide answers a question nobody asked. What
    # matters is whether the RECORD's middle is still read once the payload is
    # inflated around it. --spike-file targets one file's own midpoint, wherever
    # that file happens to sit in the assembled corpus.
    ap.add_argument("--spike-file", default="",
                    help="filename whose midpoint receives the canary; default is "
                         "the midpoint of the whole assembled corpus")
    a = ap.parse_args()

    rundir = pathlib.Path(a.rundir)
    rundir.mkdir(parents=True, exist_ok=True)
    corpus, _ = build_corpus(pathlib.Path(a.corpus))

    if a.mode == "submit":
        lo, hi = 0, len(corpus)
        if a.spike_file:
            b = corpus.find(f"===== BEGIN FILE: {a.spike_file} =====")
            e = corpus.find(f"===== END FILE: {a.spike_file} =====")
            if b < 0 or e < 0:
                print(f"--spike-file {a.spike_file!r} not found in the assembled "
                      f"corpus; refusing rather than silently spiking elsewhere",
                      file=sys.stderr)
                return 2
            lo, hi = b, e
        # Land on a paragraph boundary nearest the target midpoint, so the insert
        # reads as part of the document rather than as a splice.
        mid = (lo + hi) // 2
        breaks = [m.start() for m in re.finditer(r"\n\n", corpus)
                  if lo <= m.start() <= hi]
        cut = min(breaks, key=lambda b: abs(b - mid))
        spiked = corpus[:cut] + CANARY + corpus[cut:]
        depth = cut / len(corpus)
        print(f"corpus chars: {len(corpus):,}   canary at char {cut:,} "
              f"({depth:.1%} of the whole payload"
              f"{f', midpoint of {a.spike_file}' if a.spike_file else ''})")
        (rundir / "canary-position.json").write_text(
            json.dumps({"char": cut, "depth_pct": round(depth * 100, 2),
                        "corpus_chars": len(corpus),
                        "spike_file": a.spike_file or None}, indent=2),
            encoding="utf-8")

        payload = {
            "endpoint": "/v1/chat/completions",
            "model": a.model,
            "requests": [{
                "custom_id": "canary-01",
                "method": "POST",
                "body": {
                    "messages": [
                        {"role": "system", "content": SYSTEM},
                        {"role": "user", "content":
                            "THE COMPLETE RECORD FOLLOWS.\n" + spiked},
                        {"role": "user", "content": LENS},
                    ],
                    "max_tokens": 12000,
                    "reasoning": {"effort": "high"},
                    "provider": {"zdr": True},
                },
            }],
        }
        status, body = post(OR_BASE, payload, os.environ["OPENROUTER_API_KEY"])
        (rundir / "canary.create.json").write_text(
            json.dumps({"status": status, "body": body}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        print(f"HTTP {status}  id={body.get('id')}")
        return 0 if status < 400 else 1

    created = json.loads((rundir / "canary.create.json").read_text(encoding="utf-8"))
    status, body = get(f"{OR_BASE}/{created['body']['id']}",
                       os.environ["OPENROUTER_API_KEY"])
    (rundir / "canary.poll.json").write_text(
        json.dumps({"status": status, "body": body}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    if body.get("status") != "completed":
        print(f"batch status: {body.get('status')}")
        return 3

    msg = body["results"][0]["response"]["body"]["choices"][0]["message"]["content"]
    hits = [m for m in CANARY_MARKERS if m.lower() in msg.lower()]
    u = body.get("usage", {})
    print(f"cost ${u.get('cost'):.6f}  in={u.get('prompt_tokens'):,} "
          f"out={u.get('completion_tokens'):,}")
    print(f"canary markers found: {hits or 'NONE'}")
    print("VERDICT: " + ("READ THE MIDDLE" if len(hits) >= 2 else
                         "DID NOT SURFACE THE PLANTED FLAW — "
                         "negative findings from this lens are not trustworthy"))
    (rundir / "canary.verdict.json").write_text(
        json.dumps({"markers_found": hits, "usage": u, "answer": msg},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
