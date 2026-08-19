#!/usr/bin/env python3
"""Turn N per-lens JSON verdicts into one ranked report plus a cost/meter table.

Deliberately mechanical. The findings are merged, counted and sorted by plain
Python — no model is asked to summarise the models, because a summariser is a
second opinion wearing the costume of an aggregation, and it can invent a
finding that no lens produced.
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib

SEV_ORDER = {"fatal": 0, "serious": 1, "moderate": 2, "minor": 3}
DIFF_ORDER = {"easy": 0, "moderate": 1, "hard": 2, "impossible": 3}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parsed", required=True)
    ap.add_argument("--poll", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    data = json.loads(pathlib.Path(a.parsed).read_text(encoding="utf-8"))
    poll = json.loads(pathlib.Path(a.poll).read_text(encoding="utf-8"))["body"]

    rows: list[dict] = []
    for lens in data["parsed"]:
        for f in lens.get("findings", []):
            f = dict(f)
            f["lens"] = lens.get("lens", "?")
            rows.append(f)

    rows.sort(key=lambda f: (SEV_ORDER.get(f.get("severity"), 9),
                             DIFF_ORDER.get(f.get("cure_difficulty"), 9)))

    by_sev = collections.Counter(f.get("severity") for f in rows)
    by_lens = collections.Counter(f["lens"] for f in rows)

    L: list[str] = []
    L.append("# R04 — adversarial red team, 12 lenses over one record\n")
    L.append(f"Batch `{poll.get('id')}` · model `{poll.get('model')}` · "
             f"status `{poll.get('status')}`\n")

    u = poll.get("usage", {})
    created, finalized = poll.get("created_at"), poll.get("finalized_at")
    mins = (finalized - created) / 60 if created and finalized else None
    L.append("## The meter\n")
    L.append("| metric | value |\n|---|---:|")
    L.append(f"| items | {poll.get('request_counts', {}).get('completed')} "
             f"/ {poll.get('request_counts', {}).get('total')} |")
    L.append(f"| wall clock | {mins:.1f} min |" if mins else "| wall clock | n/a |")
    L.append(f"| prompt tokens | {u.get('prompt_tokens'):,} |")
    L.append(f"| completion tokens | {u.get('completion_tokens'):,} |")
    L.append(f"| **cost (vendor meter)** | **${u.get('cost'):.6f}** |")
    L.append("")

    # Per-item cache visibility: the standing open question is whether a shared
    # prefix inside ONE batch is ever served from cache. Report it, never assume it.
    L.append("## Cache, per item — measured, not assumed\n")
    L.append("| lens | prompt | cached | reasoning | completion |\n|---|---:|---:|---:|---:|")
    for lens in data["parsed"]:
        us = lens.get("_usage", {})
        pd = us.get("prompt_tokens_details", {}) or {}
        cd = us.get("completion_tokens_details", {}) or {}
        L.append(f"| {lens.get('lens')} | {us.get('prompt_tokens', 0):,} | "
                 f"{pd.get('cached_tokens', 0):,} | {cd.get('reasoning_tokens', 0):,} | "
                 f"{us.get('completion_tokens', 0):,} |")
    L.append("")

    L.append("## Findings by severity\n")
    L.append("| severity | n |\n|---|---:|")
    for s in ("fatal", "serious", "moderate", "minor"):
        if by_sev.get(s):
            L.append(f"| {s} | {by_sev[s]} |")
    L.append(f"\nTotal findings: **{len(rows)}** across {len(by_lens)} lenses.\n")

    L.append("## Every finding, worst first\n")
    for i, f in enumerate(rows, 1):
        L.append(f"### {i}. [{f.get('severity')}] {f.get('lens')} — "
                 f"cure: {f.get('cure_difficulty')}\n")
        L.append(f"**Officer's objection.** {f.get('attack')}\n")
        L.append(f"**Where.** {f.get('where')}\n")
        L.append(f"**Why it bites.** {f.get('why_it_bites')}\n")
        L.append(f"**Lawful cure.** {f.get('lawful_cure')}\n")

    L.append("## Per-lens verdicts\n")
    for lens in data["parsed"]:
        L.append(f"- **{lens.get('lens')}** — {lens.get('verdict')}")
        L.append(f"  - leads with: {lens.get('strongest_single_finding')}")
        L.append(f"  - gets right: {lens.get('what_the_petition_gets_right_on_this_lens')}")
    L.append("")

    if data.get("failures"):
        L.append("## Items that did not parse\n")
        for f in data["failures"]:
            L.append(f"- `{f.get('custom_id')}` — {f.get('json_error', 'no content')}")

    pathlib.Path(a.out).write_text("\n".join(L), encoding="utf-8")
    print(f"findings: {len(rows)}  severities: {dict(by_sev)}")
    print(f"written: {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
