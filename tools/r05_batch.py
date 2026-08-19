#!/usr/bin/env python3
"""R05 diff-eval batch: one item, evaluates a locally-computed Final11→Final13 delta.

Design revised 2026-08-18 after the cheap panel critique (three channels,
six independent objections). The original design (six anchored delta-aware
lenses + one side-by-side diff lens) is rejected in full for two reasons:

  1. Anchored lenses convert an INDEPENDENT adversarial test into a
     CONFIRMATION task. R04's value came from five lenses converging on the
     two-track defect WITHOUT knowledge of each other. Priming destroys that.
     Instead R05 re-runs the same 12 blind lenses as R04 via heavy_batch.py.

  2. A side-by-side diff LENS forces an LLM to do work that `difflib` does
     for $0. See tools/local_diff.py — the delta comes in pre-computed and
     the model is asked ONLY the evaluative question (motive, weakening).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("heavy_batch", HERE / "heavy_batch.py")
HB = importlib.util.module_from_spec(spec); spec.loader.exec_module(HB)  # type: ignore

OR_BASE = HB.OR_BASE
SYSTEM = HB.SYSTEM

DIFF_EVAL = """
REVIEW LENS — diff-eval

The user message above contains a UNIFIED DIFF between two revisions of the same
petition: {src} (older) and {dst} (current). The diff was produced by
`difflib.unified_diff` locally — there is no extraction task on your side.

Answer three questions IN THIS ORDER for the corpus as a whole and, when a
finding is file-specific, per file:

PART A — MOTIVE. For each material change (skip stylistic-only), name the USCIS
review criterion the change appears to invoke (a Dhanasar prong, an INA §245
sub-provision, PM-602-0199 discretion, credibility, contradiction, evidence-map).
State whether the change is well-motivated with respect to that criterion.

PART B — WEAKENING. Did any change WEAKEN the petition? Weakening includes:
  * a specific claim replaced by a vaguer one;
  * an exhibit reference dropped;
  * a favourable date window narrowed;
  * a quoted source paraphrased so the source no longer supports the framing;
  * an admission newly volunteered that no reasonable officer would have inferred;
  * a cross-document contradiction newly created (this is the primary risk when
    ONE file changes and OTHERS do not — an unchanged file may now conflict with
    a rewritten claim it used to be consistent with).

PART C — NEW ATTACK SURFACE. Independently of A and B, is there a NEW fatal or
serious USCIS attack the revision has enabled that did NOT exist in {src}?
Concretely — where in the added text does a reader find an objection the older
text did not permit? Quote the added text and name the objection.

Return JSON only, no prose fence:

{
  "lens": "diff-eval",
  "motive": [
    {"file": "...", "change_summary": "...", "criterion": "...",
     "well_motivated": "yes" | "partial" | "no", "reasoning": "..."}
  ],
  "weakening": [
    {"file": "...", "before": "...", "after": "...",
     "harm": "...", "severity": "fatal" | "serious" | "moderate" | "minor"}
  ],
  "new_attack_surface": [
    {"file": "...", "added_text": "...", "objection": "...",
     "severity": "fatal" | "serious" | "moderate" | "minor"}
  ],
  "overall_verdict": "one sentence — is {dst} a net improvement over {src}?"
}
"""


def build_diff_request(delta: str, src: str, dst: str) -> list[dict]:
    return [{
        "custom_id": "lens-diff-eval",
        "method": "POST",
        "body": {
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content":
                    f"LOCALLY-COMPUTED UNIFIED DIFF OF {src} → {dst} FOLLOWS.\n\n" + delta},
                # .replace, NOT .format — DIFF_EVAL carries a literal JSON schema
                # full of braces and .format() raises KeyError on the first one.
                {"role": "user", "content":
                    DIFF_EVAL.replace("{src}", src).replace("{dst}", dst)},
            ],
            "max_tokens": 16000,
            "reasoning": {"effort": "high"},
            "provider": {"zdr": True},
        },
    }]


def submit(payload: dict, tag: str, rundir: pathlib.Path, key: str) -> int:
    raw = json.dumps(payload)
    print(f"items: {len(payload['requests'])}   payload bytes: {len(raw):,}")
    status, body = HB.post(OR_BASE, payload, key)
    (rundir / f"{tag}.create.json").write_text(
        json.dumps({"status": status, "body": body}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(f"HTTP {status}  id={body.get('id')}")
    if status >= 400:
        print(json.dumps(body, indent=2)[:2000])
        return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rundir", required=True)
    ap.add_argument("--delta", required=True, help="path to a delta.md produced by local_diff.py")
    ap.add_argument("--model", default="google/gemini-3.7-flash:batch")
    ap.add_argument("--tag", default="diff-eval")
    # R06 shipped with these two hardcoded to Final11/Final13 while the delta was
    # actually Final13->Final14. Required now, so the mismatch cannot recur silently.
    ap.add_argument("--from-label", required=True, help="label of the OLDER revision")
    ap.add_argument("--to-label", required=True, help="label of the NEWER revision")
    a = ap.parse_args()

    rundir = pathlib.Path(a.rundir)
    rundir.mkdir(parents=True, exist_ok=True)
    key = os.environ["OPENROUTER_API_KEY"]

    delta = pathlib.Path(a.delta).read_text(encoding="utf-8")
    # Cheap guard against the R06 failure: if the bundle header names versions and
    # they disagree with the labels passed here, stop rather than mislabel again.
    head = delta[:200]
    for lbl in (a.from_label, a.to_label):
        if lbl not in head:
            print(f"REFUSING: delta bundle header does not mention {lbl!r}.\n"
                  f"  header: {head.splitlines()[0][:120]!r}\n"
                  f"  Pass labels that match the bundle, or regenerate the bundle.")
            return 2

    payload = {
        "endpoint": "/v1/chat/completions",
        "model": a.model,
        "requests": build_diff_request(delta, a.from_label, a.to_label),
    }
    print(f"labels: {a.from_label} -> {a.to_label}")
    return submit(payload, a.tag, rundir, key)


if __name__ == "__main__":
    raise SystemExit(main())
