#!/usr/bin/env python3
"""Compare R04's per-lens findings against R05's blind re-run of the same lenses.

Mechanical only. Groups findings by lens and severity, computes deltas.
Does NOT decide "cured / persists / weakened" — that judgement is on the
reader with both sets in front of them. This script prepares the evidence.

Output is a Markdown grid the aggregator hands to the reader.
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib


SEV_ORDER = {"fatal": 0, "serious": 1, "moderate": 2, "minor": 3}


def load_findings(p: pathlib.Path) -> dict[str, list[dict]]:
    d = json.loads(p.read_text(encoding="utf-8"))
    per_lens: dict[str, list[dict]] = collections.defaultdict(list)
    for lens in d.get("parsed", []):
        lens_id = lens.get("lens", "?")
        for f in lens.get("findings", []):
            per_lens[lens_id].append({
                "severity": f.get("severity"),
                "attack": (f.get("attack") or "").strip(),
                "where": (f.get("where") or "").strip(),
                "cure": (f.get("lawful_cure") or "").strip(),
            })
    return per_lens


def count_sev(per_lens: dict[str, list[dict]]) -> dict[str, collections.Counter]:
    return {l: collections.Counter(f["severity"] for f in fs) for l, fs in per_lens.items()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--r04", required=True, help="path to R04 salvaged/parsed json")
    ap.add_argument("--r05", required=True, help="path to R05 salvaged/parsed json")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    a04 = load_findings(pathlib.Path(a.r04))
    a05 = load_findings(pathlib.Path(a.r05))
    c04, c05 = count_sev(a04), count_sev(a05)

    lenses = sorted(set(a04) | set(a05))

    L: list[str] = []
    L.append("# R04 → R05 regression grid\n")
    L.append("Mechanical comparison of the same 12 blind lenses over the "
             "Final11 (R04) and Final13 (R05) corpora. Same code path, same "
             "prompt schema, no anchoring across runs.\n")

    L.append("## Severity counts by lens\n")
    L.append("| lens | R04 fatal | R04 serious | R04 moderate | R04 minor | "
             "R05 fatal | R05 serious | R05 moderate | R05 minor | Δ fatal |")
    L.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    tot04 = collections.Counter()
    tot05 = collections.Counter()
    for lens in lenses:
        c4, c5 = c04.get(lens, collections.Counter()), c05.get(lens, collections.Counter())
        for s in ("fatal", "serious", "moderate", "minor"):
            tot04[s] += c4[s]; tot05[s] += c5[s]
        L.append(
            f"| {lens} | {c4['fatal']} | {c4['serious']} | {c4['moderate']} | {c4['minor']} | "
            f"{c5['fatal']} | {c5['serious']} | {c5['moderate']} | {c5['minor']} | "
            f"{c5['fatal'] - c4['fatal']:+d} |"
        )
    L.append(
        f"| **total** | **{tot04['fatal']}** | **{tot04['serious']}** | **{tot04['moderate']}** | "
        f"**{tot04['minor']}** | **{tot05['fatal']}** | **{tot05['serious']}** | "
        f"**{tot05['moderate']}** | **{tot05['minor']}** | "
        f"**{tot05['fatal'] - tot04['fatal']:+d}** |"
    )
    L.append("")

    L.append("## Fatal findings, side by side by lens\n")
    for lens in lenses:
        r04_fatals = [f for f in a04.get(lens, []) if f["severity"] == "fatal"]
        r05_fatals = [f for f in a05.get(lens, []) if f["severity"] == "fatal"]
        if not r04_fatals and not r05_fatals:
            continue
        L.append(f"### {lens}\n")
        L.append("**R04 fatals:**\n")
        if r04_fatals:
            for f in r04_fatals:
                L.append(f"- **{f['where'][:80]}**")
                L.append(f"  - {f['attack'][:280]}")
        else:
            L.append("- (none)\n")
        L.append("\n**R05 fatals:**\n")
        if r05_fatals:
            for f in r05_fatals:
                L.append(f"- **{f['where'][:80]}**")
                L.append(f"  - {f['attack'][:280]}")
        else:
            L.append("- (none — potential cure or non-recurrence)\n")
        L.append("")

    L.append("## Fatal-lens verdict summary\n")
    L.append("| lens | R04 fatal count | R05 fatal count | outcome (mechanical) |")
    L.append("|---|---:|---:|---|")
    for lens in lenses:
        n4 = c04.get(lens, collections.Counter())["fatal"]
        n5 = c05.get(lens, collections.Counter())["fatal"]
        if n4 and n5:
            outcome = "persists" + (f" (worse: {n4}→{n5})" if n5 > n4 else
                                     f" (fewer: {n4}→{n5})" if n5 < n4 else " (same count)")
        elif n4 and not n5:
            outcome = "possibly cured (no R05 fatal on this lens)"
        elif n5 and not n4:
            outcome = "**NEW fatal not present in R04**"
        else:
            outcome = "no fatal either run"
        L.append(f"| {lens} | {n4} | {n5} | {outcome} |")
    L.append("")
    L.append("**Reader — do not read 'possibly cured' as 'cured'.** A blind lens "
             "returning no fatal in R05 could mean the defect is gone, or that "
             "the model happened not to converge on it this time. Confirm by "
             "reading the R05 lens output.\n")

    pathlib.Path(a.out).write_text("\n".join(L), encoding="utf-8")
    print(f"written: {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
