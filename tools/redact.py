#!/usr/bin/env python3
"""Tokenise PII out of a document corpus before it leaves the project.

Two modes.

  --propose   Read the corpus, find capitalised names that sit next to
              natural-person markers ("letter from", "Dr.", "attests"),
              skip anything that reads as published caselaw ("Matter of X",
              "X v. Y", "I&N Dec."), and write a DRAFT map for a human to
              review. Proposing is not deciding: nothing is sent from this mode.

  --apply     Apply a reviewed map plus structured-PII regexes, write the
              redacted corpus, then RE-SCAN THE OUTPUT and report anything
              that still matches a PII pattern. The re-scan is the point:
              a redactor that cannot show its own residue is a claim, not a check.

The map holds the very PII it removes, so it lives in a gitignored path.
This file does not, and must never contain a literal from the case.

Policy implemented (project CLAUDE.md, "Publication boundary"):
  CUT  full name, A-number, receipt/SEVIS/I-94 numbers, apartment or unit
       number, phone, email, any third party's name.
  KEEP street, city, ZIP5, county, school and institution names — a reviewer
       cannot check "this neighbourhood lies inside that city" against a token.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import unicodedata

# --------------------------------------------------------------------------
# structured PII: shapes that are identifying no matter what the map says
# --------------------------------------------------------------------------
STRUCTURED: list[tuple[str, re.Pattern, str]] = [
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), "[EMAIL]"),
    ("a_number", re.compile(r"\bA-?\d{3}-?\d{3}-?\d{3}\b"), "[A-NUMBER]"),
    ("sevis", re.compile(r"\bN\d{10}\b"), "[SEVIS]"),
    ("receipt", re.compile(r"\b[A-Z]{3}-?\d{3,4}-?\d{3}-?\d{3}(?:-?\d)?\b"), "[RECEIPT]"),
    # I-94 comes in two shapes in the wild: 11 digits, and 9 digits + letter + digit.
    ("i94", re.compile(r"\b\d{9}[A-Z]\d\b|\b\d{11}\b"), "[I-94]"),
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[SSN]"),
    ("phone", re.compile(r"\(?\b\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b"), "[PHONE]"),
    # Unit number turns a street into a household; the street itself is geography.
    #
    # MEASURED 2026-08-17 — the first version of this rule was
    #     r",?\s*(?:Apt|Apartment|Unit|Ste|Suite|#)\.?\s*[\w-]+"
    # and it destroyed the corpus while the audit reported CLEAN:
    #   * no \b, so "Ste" matched inside "li|ste|d" and "Unit" inside "Unit|ed"
    #     -> all 90 occurrences of "United States" became " States";
    #   * "#" is an apartment marker in an address and a heading marker in
    #     Markdown, so "## Exhibit M-4" became "# M-4" -> 259 headings became 38;
    #   * \s* crosses newlines, so a match starting on one line ate the heading
    #     two lines below it.
    # Hence: word boundaries, horizontal whitespace only, a DIGIT required in the
    # unit token, and "#" accepted only after a comma where an address puts it.
    ("unit", re.compile(
        r",?[^\S\n]*\b(?:Apt|Apartment|Unit|Ste|Suite)\b\.?[^\S\n]*#?[^\S\n]*"
        r"[A-Za-z]?\d+[A-Za-z]?\b", re.I), ""),
    ("unit_hash", re.compile(r",[^\S\n]*#[^\S\n]*\d+[A-Za-z]?\b"), ""),
    # ZIP+4 resolves to a single building face; the 5-digit ZIP does not.
    ("zip4", re.compile(r"\b(\d{5})-\d{4}\b"), r"\1"),
]

# --------------------------------------------------------------------------
# person detection, for --propose only
# --------------------------------------------------------------------------
NAME = re.compile(r"\b[A-Z][a-z]{1,}(?:['’\-][A-Z]?[a-z]+)*(?:\s+[A-Z][a-z]{1,}(?:['’\-][A-Z]?[a-z]+)*){1,2}\b")

PERSON_MARKER = re.compile(
    r"\b(?:letter|letters|recommendation|recommender|attest\w*|declaration|"
    r"affidavit|signed|signature|wrote|writes|testimon\w*|colleague|supervisor|"
    r"manager|mentor|professor|instructor|teacher|founder|co-?founder|partner|"
    r"coworker|co-?worker|referee|attorney|counsel|notary|witness|spouse|wife|"
    r"husband|son|daughter|father|mother|brother|sister|Dr|Prof|Mr|Ms|Mrs|Miss|"
    r"PhD|Ph\.D|M\.D|Esq|CEO|CTO|President|Director|Principal)\b",
    re.I,
)

# Published caselaw is a person's name in form only. Redacting it destroys the
# very argument the reviewer is asked to test.
CASELAW = re.compile(
    r"(?:\bMatter\s+of\b|\bIn\s+re\b|\bv\.\s|\s+v\.\b|\bI&N\s+Dec\b|\bF\.\s*(?:2d|3d|4th|Supp)\b|"
    r"\bCir\.|\bBIA\b|\bAAO\b|\bU\.S\.\s+\d)",
    re.I,
)

ORG_MARKER = re.compile(
    r"\b(?:LLC|L\.L\.C|Inc|Corp\w*|Company|Co\.|Ltd|LLP|PLLC|Foundation|Institute|"
    r"University|College|School|Center|Centre|Academy|Association|Society|Council|"
    r"Department|Bureau|Office|Agency|Services?|Systems|Technologies|Group|Partners|"
    r"Fund|Trust|Union|Committee|Board|Commission|Court|Embassy|Consulate|Ministry|"
    r"Republic|Register|Manual|Act|Code|Circuit|District|County|City|State)\b",
    re.I,
)

WINDOW = 60  # chars either side that count as "next to" a marker


def _norm(s: str) -> str:
    return unicodedata.normalize("NFC", s)


TITLES = ("Dr.", "Dr", "Prof.", "Prof", "Mr.", "Ms.", "Mrs.")


def derive_variants(full: str, also: list[str] | None = None) -> list[str]:
    """Every written form one person's name takes in a filing.

    "Firstname Surname" -> that, plus "F. Surname", "F Surname",
    "Dr. Surname", "Surname". `also` carries spellings a rule cannot
    predict — misspellings, transliterations, maiden names.
    """
    out: set[str] = {full}
    out.update(also or [])
    parts = full.split()
    if len(parts) >= 2:
        first, last = parts[0], parts[-1]
        out.add(last)
        out.add(f"{first[0]}. {last}")
        out.add(f"{first[0]} {last}")
        for t in TITLES:
            out.add(f"{t} {last}")
        if len(parts) > 2:  # middle name present: also the first+last pair
            out.add(f"{first} {last}")
    # Longest first so "Dr. Firstname Surname" is consumed before "Surname".
    return sorted(out, key=len, reverse=True)


def load_corpus(root: pathlib.Path, pattern: str) -> dict[str, str]:
    return {p.name: _norm(p.read_text(encoding="utf-8")) for p in sorted(root.glob(pattern))}


def propose(corpus: dict[str, str], out: pathlib.Path) -> None:
    hits: dict[str, dict] = {}
    for fname, text in corpus.items():
        for m in NAME.finditer(text):
            phrase = re.sub(r"\s+", " ", m.group(0))
            lo, hi = max(0, m.start() - WINDOW), min(len(text), m.end() + WINDOW)
            ctx = text[lo:hi]
            if CASELAW.search(ctx):
                continue
            # An organisation word in the WINDOW must not suppress: a real person is
            # normally introduced together with their institution ("Dr. X of Y
            # University"), which is exactly the highest-signal case. Only an org
            # marker inside the phrase itself means the phrase is an organisation.
            # (Measured 2026-08-17: the window form dropped a genuine recommender.)
            if ORG_MARKER.search(phrase):
                continue
            if not PERSON_MARKER.search(ctx):
                continue
            rec = hits.setdefault(phrase, {"phrase": phrase, "count": 0, "files": set(), "samples": []})
            rec["count"] += 1
            rec["files"].add(fname)
            if len(rec["samples"]) < 2:
                rec["samples"].append(re.sub(r"\s+", " ", ctx).strip())

    ranked = sorted(hits.values(), key=lambda r: -r["count"])
    for r in ranked:
        r["files"] = sorted(r["files"])
        r["decision"] = "REVIEW"  # REDACT | KEEP | REVIEW
        r["token"] = ""

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "_instructions": "Set decision to REDACT (+ a role-preserving token "
                                 "like [RECOMMENDER-1]) or KEEP. Anything left as REVIEW "
                                 "makes --apply refuse to run.",
                "candidates": ranked,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"person-marker-adjacent candidates: {len(ranked)}")
    print(f"draft map written: {out}")


def apply(corpus: dict[str, str], mapfile: pathlib.Path, outdir: pathlib.Path,
          auditfile: pathlib.Path) -> int:
    cfg = json.loads(mapfile.read_text(encoding="utf-8"))
    literals: list[tuple[str, str]] = []

    for k, v in cfg.get("literals", {}).items():
        literals.append((k, v))

    # A person's name is not one string. The same recommender appears as
    # "Firstname Surname", "F. Surname", "Dr. Surname" and bare "Surname" — and a
    # literal-only map removes the first and leaves the rest, which are just as
    # identifying. Derive the variants from the full name so the map cannot
    # silently under-redact.
    for p in cfg.get("persons", []):
        token = p["token"]
        for v in derive_variants(p["full"], p.get("also", [])):
            literals.append((v, token))

    for c in cfg.get("candidates", []):
        if c.get("decision") == "REVIEW":
            print(f"REFUSING: candidate still marked REVIEW: {c['phrase']!r}", file=sys.stderr)
            return 2
        if c.get("decision") == "REDACT":
            if not c.get("token"):
                print(f"REFUSING: REDACT with no token: {c['phrase']!r}", file=sys.stderr)
                return 2
            literals.append((c["phrase"], c["token"]))

    # Longest first, so a full "First Last" is consumed before a bare "Last".
    literals.sort(key=lambda kv: -len(kv[0]))

    # A domain or a code-host handle carries the same name an email does, and no
    # structured rule sees it: a vanity domain built from the applicant's own name
    # survived every pattern above, because it has no "@" and no digits.
    handles = cfg.get("handles", {})
    handle_rules = [
        (h, re.compile(rf"\b{re.escape(h)}\b", re.I), tok) for h, tok in handles.items()
    ]

    counts: dict[str, int] = {}
    outdir.mkdir(parents=True, exist_ok=True)

    for fname, text in corpus.items():
        for needle, token in literals:
            n = text.count(needle)
            if n:
                counts[f"literal:{needle[:3]}***"] = counts.get(f"literal:{needle[:3]}***", 0) + n
                text = text.replace(needle, token)
        for label, rx, repl in STRUCTURED:
            text, n = rx.subn(repl, text)
            if n:
                counts[f"regex:{label}"] = counts.get(f"regex:{label}", 0) + n
        for h, rx, tok in handle_rules:
            text, n = rx.subn(tok, text)
            if n:
                counts[f"handle:{h[:3]}***"] = counts.get(f"handle:{h[:3]}***", 0) + n
        (outdir / fname).write_text(text, encoding="utf-8")

    # ---- residual scan: re-read what was WRITTEN, not what we think we wrote --
    residual: list[dict] = []
    for path in sorted(outdir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        for label, rx, _ in STRUCTURED:
            if label in ("zip4", "unit"):
                continue  # these rewrite rather than remove; a match is expected
            for m in rx.finditer(text):
                residual.append({"file": path.name, "pattern": label,
                                 "match": m.group(0)[:4] + "***", "pos": m.start()})
        for needle, _ in literals:
            if needle in text:
                residual.append({"file": path.name, "pattern": "literal-survived",
                                 "match": needle[:3] + "***", "pos": text.index(needle)})

    # ---- damage scan --------------------------------------------------------
    # A residue scan alone certifies a DESTROYED document as safe: on 2026-08-17
    # a greedy unit-number rule deleted every "United" and 221 of 259 Markdown
    # headings, and the residue scan still printed CLEAN. Redaction has two
    # failure modes, not one, and only one of them is about PII.
    HEADING = re.compile(r"(?m)^#{1,6}\s")
    damage: list[dict] = []
    canaries: list[str] = cfg.get("canaries", [])

    for fname, before in corpus.items():
        after = (outdir / fname).read_text(encoding="utf-8")
        b_head, a_head = len(HEADING.findall(before)), len(HEADING.findall(after))
        if b_head != a_head:
            damage.append({"file": fname, "kind": "headings",
                           "before": b_head, "after": a_head})
        b_lines, a_lines = before.count("\n"), after.count("\n")
        if b_lines != a_lines:
            damage.append({"file": fname, "kind": "line_count",
                           "before": b_lines, "after": a_lines})
        for phrase in canaries:
            b_n, a_n = before.count(phrase), after.count(phrase)
            if b_n != a_n:
                damage.append({"file": fname, "kind": "canary", "phrase": phrase,
                               "before": b_n, "after": a_n})

    verdict = "CLEAN"
    if residual:
        verdict = "RESIDUE — DO NOT SEND"
    elif damage:
        verdict = "DAMAGE — DO NOT SEND"

    audit = {
        "source_files": len(corpus),
        "literal_rules": len(literals),
        "replacements": counts,
        "residual_hits": len(residual),
        "residual": residual[:200],
        "damage_hits": len(damage),
        "damage": damage[:200],
        "canaries_checked": canaries,
        "verdict": verdict,
    }
    auditfile.parent.mkdir(parents=True, exist_ok=True)
    auditfile.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"redacted {len(corpus)} files -> {outdir}")
    print(f"replacements: {sum(counts.values())} across {len(counts)} rule(s)")
    print(f"RESIDUAL: {len(residual)}   DAMAGE: {len(damage)}   verdict: {verdict}")
    print(f"audit: {auditfile}")
    return 0 if verdict == "CLEAN" else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--glob", default="*.md")
    ap.add_argument("--propose", metavar="DRAFT_MAP")
    ap.add_argument("--map")
    ap.add_argument("--outdir")
    ap.add_argument("--audit")
    a = ap.parse_args()

    corpus = load_corpus(pathlib.Path(a.corpus), a.glob)
    if not corpus:
        print("empty corpus", file=sys.stderr)
        return 2

    if a.propose:
        propose(corpus, pathlib.Path(a.propose))
        return 0
    if not (a.map and a.outdir and a.audit):
        ap.error("--apply needs --map, --outdir and --audit")
    return apply(corpus, pathlib.Path(a.map), pathlib.Path(a.outdir), pathlib.Path(a.audit))


if __name__ == "__main__":
    raise SystemExit(main())
