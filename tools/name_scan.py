#!/usr/bin/env python3
"""Offline candidate-name scanner for a document corpus.

Extracts capitalised n-grams so a human can sort them into
"organisation / place -> keep" and "natural person -> redact".
Reads nothing over the network and writes no PII into the repo tree:
the output goes wherever --out points, which must be a gitignored path.
"""
import argparse
import collections
import json
import pathlib
import re

# A capitalised run of 2-4 words, allowing internal lowercase particles.
NGRAM = re.compile(
    r"\b[A-Z][a-zA-Z'’\-]+(?:\s+(?:of|de|van|von|der|the|and)\s+|\s+)"
    r"[A-Z][a-zA-Z'’\-]+(?:(?:\s+(?:of|de|van|von|der|the|and)\s+|\s+)"
    r"[A-Z][a-zA-Z'’\-]+){0,2}"
)

# Anything ending in one of these is an organisation, not a natural person.
ORG_SUFFIX = re.compile(
    r"\b(?:LLC|L\.L\.C|Inc|Corp|Corporation|Company|Co|Ltd|LLP|PLLC|Foundation|"
    r"Institute|University|College|School|Center|Centre|Academy|Association|"
    r"Society|Council|Department|Bureau|Office|Agency|Service|Services|Systems|"
    r"Technologies|Group|Partners|Fund|Trust|Union|Committee|Board|Commission|"
    r"Court|Circuit|Embassy|Consulate|Ministry|Republic|States|District)\b\.?$"
)

# Legal, governmental and doc-structure vocabulary that will otherwise flood the list.
STOP_PHRASES = {
    "United States", "Department of State", "Department of Homeland Security",
    "Homeland Security", "Immigration and Nationality Act", "Nationality Act",
    "Policy Manual", "Federal Register", "Code of Federal Regulations",
    "Matter of Dhanasar", "Matter of New", "Administrative Appeals Office",
    "Board of Immigration", "Supreme Court", "Ninth Circuit", "Los Angeles",
    "New York", "Republic of Belarus", "Statement of Intent", "Cover Letter",
    "Table of Contents", "National Interest", "National Interest Waiver",
    "Adjustment of Status", "Permanent Residence", "Green Card",
    "Advanced Degree", "Exceptional Ability", "Labor Certification",
    "Request for Evidence", "Notice of Intent", "Intent to Deny",
    "Employment Authorization", "Advance Parole", "Social Security",
    "Artificial Intelligence", "Machine Learning", "Small Business",
    "United States Citizenship", "Citizenship and Immigration",
    "Immigration Services", "Service Center", "Field Office",
}

TITLE_PREFIX = re.compile(r"^(?:Dr|Prof|Mr|Ms|Mrs|Miss|Hon|Rev|Sir)\.?\s+")


def classify(phrase: str) -> str:
    if phrase in STOP_PHRASES:
        return "stop"
    if ORG_SUFFIX.search(phrase):
        return "org"
    if TITLE_PREFIX.match(phrase):
        return "person-titled"
    words = phrase.split()
    # Two bare capitalised words with no org marker: the shape a person's name takes.
    if len(words) == 2:
        return "person-candidate"
    return "other"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--glob", default="*.md")
    ap.add_argument("--out", required=True)
    ap.add_argument("--min-count", type=int, default=1)
    args = ap.parse_args()

    counts: collections.Counter = collections.Counter()
    where: dict[str, set[str]] = collections.defaultdict(set)

    for path in sorted(pathlib.Path(args.corpus).glob(args.glob)):
        text = path.read_text(encoding="utf-8")
        # Drop markdown heading markers so "## Purpose" does not read as a name.
        text = re.sub(r"^#{1,6}\s+", "", text, flags=re.M)
        for m in NGRAM.finditer(text):
            phrase = re.sub(r"\s+", " ", m.group(0)).strip()
            counts[phrase] += 1
            where[phrase].add(path.name)

    buckets: dict[str, list] = collections.defaultdict(list)
    for phrase, n in counts.most_common():
        if n < args.min_count:
            continue
        buckets[classify(phrase)].append(
            {"phrase": phrase, "count": n, "files": sorted(where[phrase])}
        )

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "corpus": args.corpus,
                "distinct_phrases": len(counts),
                "buckets": {k: len(v) for k, v in buckets.items()},
                "candidates": buckets,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"distinct phrases: {len(counts)}")
    for k in sorted(buckets):
        print(f"  {k}: {len(buckets[k])}")
    print(f"written: {out}")


if __name__ == "__main__":
    main()
