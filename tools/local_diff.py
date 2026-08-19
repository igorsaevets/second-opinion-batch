#!/usr/bin/env python3
"""Compute the delta between two corpus revisions locally.

Rationale (2026-08-18 panel — agy37flash):
    "Paying ~$0.08 to extract a delta that a deterministic local script
    (`diff -u` or git diff) computes instantly at $0.00 cost wastes more
    than a third of the entire R05 budget."

Output is a delta bundle: one section per file that changed, containing the
unified diff and just enough surrounding context that a reviewer can judge
the change without seeing the whole corpus. Files with zero delta are
listed by name only.

Consumed by r05_batch.py in `--mode diff-eval`.

🔴 2026-08-18, R07 — the labels used to be the literals "Final11" and "Final13".
R06 diffed Final13→Final14 through this script and every label in the bundle,
and therefore every label in the model's prose, was one version behind. The
findings were semantically right and named the wrong files, which is the worst
kind of wrong: it reads as correct. Labels are now derived from the directory
name and overridable, and NOTHING here may name a version literal again.
"""
from __future__ import annotations

import argparse
import difflib
import pathlib


def bundle(src: pathlib.Path, dst: pathlib.Path, ctx: int,
           src_label: str, dst_label: str) -> str:
    parts: list[str] = []
    parts.append(f"# {src_label} → {dst_label} delta "
                 f"(locally computed, deterministic).\n\n")

    src_files = {p.name: p for p in src.glob("*.md")}
    dst_files = {p.name: p for p in dst.glob("*.md")}

    only_src = sorted(set(src_files) - set(dst_files))
    only_dst = sorted(set(dst_files) - set(src_files))
    common = sorted(set(src_files) & set(dst_files))

    if only_src:
        parts.append(f"## Files removed in {dst_label}\n" +
                     "\n".join(f"- {n}" for n in only_src) + "\n\n")
    if only_dst:
        parts.append(f"## Files added in {dst_label}\n" +
                     "\n".join(f"- {n}" for n in only_dst) + "\n\n")

    unchanged: list[str] = []
    parts.append("## Per-file diffs (unchanged files listed at end)\n\n")

    for name in common:
        a = src_files[name].read_text(encoding="utf-8").splitlines(keepends=False)
        b = dst_files[name].read_text(encoding="utf-8").splitlines(keepends=False)
        if a == b:
            unchanged.append(name)
            continue
        diff = list(difflib.unified_diff(
            a, b,
            fromfile=f"{src_label}/{name}",
            tofile=f"{dst_label}/{name}",
            n=ctx, lineterm="",
        ))
        parts.append(f"### {name}\n")
        parts.append(f"{src_label} lines: {len(a):,}   {dst_label} lines: {len(b):,}   "
                     f"delta: {len(b) - len(a):+,}\n\n")
        parts.append("```diff\n" + "\n".join(diff) + "\n```\n\n")

    if unchanged:
        parts.append("## Unchanged files\n" +
                     "\n".join(f"- {n}" for n in unchanged) + "\n")
    return "".join(parts)


def derive_label(d: pathlib.Path) -> str:
    """`private/final14-redacted` -> `Final14`. A directory that does not carry a
    version in its name keeps its own name — better an ugly true label than a
    pretty false one."""
    stem = d.resolve().name
    for suffix in ("-redacted", "-source", "-clean"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    return stem[:1].upper() + stem[1:] if stem else stem


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="src", required=True,
                    help="older revision directory")
    ap.add_argument("--to", dest="dst", required=True,
                    help="newer revision directory")
    ap.add_argument("--from-label", default="",
                    help="label for the older revision; default: derived from dir name")
    ap.add_argument("--to-label", default="",
                    help="label for the newer revision; default: derived from dir name")
    ap.add_argument("--out", required=True)
    ap.add_argument("--context", type=int, default=3)
    a = ap.parse_args()

    src, dst = pathlib.Path(a.src), pathlib.Path(a.dst)
    src_label = a.from_label or derive_label(src)
    dst_label = a.to_label or derive_label(dst)

    text = bundle(src, dst, a.context, src_label, dst_label)
    out = pathlib.Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)   # R06: this used to FileNotFoundError
    out.write_text(text, encoding="utf-8")
    print(f"delta bundle: {a.out}   chars: {len(text):,}")
    print(f"labels: {src_label} -> {dst_label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
