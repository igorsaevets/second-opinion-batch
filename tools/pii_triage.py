#!/usr/bin/env python3
"""Triage redact.py's candidate list into KEEP / CUT / REVIEW without asking a model.

THE PROBLEM
`redact.py --propose` over the enlarged corpus returned 1,135 person-marker-adjacent
candidates. Most are not people: "Attorney General" (108x), "United States" (80x),
"Executive Director", "Risk Management", "Product Manager Course". Cutting those would
destroy the document — and this project has already measured exactly that failure: a
redaction pass once deleted all 83 occurrences of "United States" and 221 of 259 headings
and still printed CLEAN, because the checker only asked "did PII survive?" and never
"did the document survive?".

THE DISCRIMINATOR
A surname appears in a corpus ONLY capitalised. A common noun that happens to be
capitalised inside a title — General, States, Director, Management, Information — also
appears in lowercase, constantly, in ordinary prose. So: build the corpus's own lowercase
vocabulary, then ask of each candidate phrase whether every one of its words is attested in
lowercase. If yes, it is a title or a phrase, not a person. If some word never appears in
lowercase, that word is a proper noun and the phrase is person-like.

This needs no wordlist, no language model and no network — the corpus supplies its own
frequency baseline, which is why it works on Russian and English alike. It is a heuristic,
so it emits a REVIEW bucket rather than pretending to be certain, and the two-sided audit
downstream is still what actually gates sending.

Read-only apart from the map it writes. No network, no spend.
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import re

WORD = re.compile(r"[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё'’\-]*")

# Phrases that are institutions, offices, geography or law. CLAUDE.md is explicit that these
# STAY: "Keep: street, city, ZIP, county, institution names" — a reviewer cannot verify
# "this neighbourhood lies inside that city" against a token. Matched as substrings,
# case-insensitively, because "the Attorney General" and "Attorney General" are one thing.
KEEP_MARKERS = re.compile(
    r"united states|attorney general|homeland security|executive order|"
    r"department|secretary of|service center|supreme court|court of appeals|"
    r"congress|senate|white house|president trump|uscis|dhs|ice\b|sevp|sevis|"
    r"immigration|nationality act|federal|national|university|college|institute|"
    r"school|academy|company|corporation|\bllc\b|\binc\b|foundation|association|"
    r"bureau|office of|board of|state of|city of|county",
    re.I)

# Roles and generic business/legal noun phrases that the marker heuristic drags in.
ROLE_TAIL = re.compile(
    r"\b(director|president|manager|officer|secretary|counsel|attorney|judge|"
    r"chair|chief|founder|scientist|professor|engineer|instructor|representative|"
    r"course|training|program|letter|championship|testimony|assessment|evaluation|"
    r"management|information|contribution|importance|shortages|degree|order|"
    r"engineering|incubator|brief)\b", re.I)

# ---------------------------------------------------------------------------------
# The lowercase test alone OVER-CUTS, and its first run proved it: it sentenced
# "New York", "Los Angeles", "Valentine's Day", "Preparer's Signature" and "Dear Mr" to
# tokens. "York" and "Angeles" genuinely never appear in lowercase — they are proper nouns.
# They are simply not PEOPLE. So the rare-word signal answers "is this a proper noun?",
# never "is this a person", and the three classes below are the proper nouns that must
# survive. CLAUDE.md is explicit that geography and institutions stay: a reviewer cannot
# check "this neighbourhood lies inside that city" against a token.
# ---------------------------------------------------------------------------------

# Place names. Cutting these breaks every venue, jurisdiction and address check in the
# record, and an address minus its unit number is geography, not identity.
# Deliberately ORDINARY WORLD GEOGRAPHY only. The specific districts, streets and
# institutions of whichever case is being processed are not listed here: this file is
# public-by-destination, and a stoplist naming a claimant's home street identifies them
# just as surely as their name does. Case-specific terms go in a private file passed via
# --extra-keep, so the tool ships without knowing whose record it last handled.
GEO = re.compile(
    r"\b(new york|los angeles|san francisco|san jose|washington|california|"
    r"nevada|texas|florida|virginia|maryland|delaware|arizona|oregon|"
    r"minsk|belarus|moscow|russia|ukraine|kazakhstan|poland|warsaw|milano|milan|"
    r"italy|germany|berlin|london|hollywood|"
    r"burbank|glendale|pasadena|santa monica|beverly hills|brooklyn|manhattan|"
    r"queens|bronx|rochester|nebraska|missouri|vermont|"
    r"main st|broadway)\b", re.I)

# Form scaffolding. An I-485 is 458 filled widgets whose LABELS are capitalised bigrams;
# tokenising them turns a readable form into noise and invites "Part 3 left blank".
FORM_LABEL = re.compile(
    r"\b(signature|preparer|interpreter|applicant|petitioner|beneficiary|"
    r"part\b|line\b|item\b|page\b|section\b|checkbox|date signed|"
    r"family name|given name|middle name|mailing address|physical address|"
    r"apt\b|ste\b|flr\b|receipt|notice|form\b|expires?)\b", re.I)

# Salutations, closings and calendar words that sit next to person markers by definition.
EPISTOLARY = re.compile(
    r"^(dear|sincerely|regards|respectfully|to whom|yours)\b|"
    r"\b(day|week|month|year|monday|tuesday|wednesday|thursday|friday|"
    r"saturday|sunday|january|february|march|april|may|june|july|august|"
    r"september|october|november|december|summit|conference|award|prize)\b", re.I)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--draft", required=True, help="output of redact.py --propose")
    ap.add_argument("--corpus", required=True, help="dir holding the corpus text files")
    ap.add_argument("--glob", default="tier-*.txt")
    ap.add_argument("--out", required=True)
    ap.add_argument("--min-lower", type=int, default=3,
                    help="lowercase occurrences at which a word counts as a common word")
    ap.add_argument("--applicant", action="append", default=[],
                    help="repeatable; phrases that are the applicant, always CUT")
    ap.add_argument("--extra-keep", default="",
                    help="path to a PRIVATE newline-separated list of case-specific terms "
                         "that must survive redaction — the claimant's street, their "
                         "school, the district they were born in. These are geography and "
                         "institutions, which CLAUDE.md keeps, but naming them in this "
                         "file would identify the case, so they live outside the repo.")
    a = ap.parse_args()

    extra_keep = None
    if a.extra_keep:
        terms = [t.strip() for t in pathlib.Path(a.extra_keep).read_text(
            encoding="utf-8").splitlines() if t.strip() and not t.startswith("#")]
        if terms:
            extra_keep = re.compile("|".join(re.escape(t) for t in terms), re.I)
            print(f"extra-keep: {len(terms)} case-specific terms loaded (not logged)")

    # ---- the corpus's own lowercase vocabulary ------------------------------------
    lower = collections.Counter()
    files = sorted(pathlib.Path(a.corpus).glob(a.glob))
    for f in files:
        text = f.read_text(encoding="utf-8", errors="replace")
        for m in WORD.finditer(text):
            w = m.group(0)
            if w[:1].islower():
                lower[w.lower()] += 1
    print(f"lowercase vocabulary: {len(lower):,} distinct words from {len(files)} files")

    draft = json.loads(pathlib.Path(a.draft).read_text(encoding="utf-8"))
    cands = draft["candidates"]

    applicant_rx = [re.compile(re.escape(x), re.I) for x in a.applicant]

    buckets = {"CUT": [], "KEEP": [], "REVIEW": []}
    person_n = 0
    for c in cands:
        phrase = c["phrase"]
        words = WORD.findall(phrase)
        if not words:
            c["decision"] = "KEEP"
            buckets["KEEP"].append(c)
            continue

        if any(rx.search(phrase) for rx in applicant_rx):
            c["decision"] = "CUT"
            c["_why"] = "applicant"
            buckets["CUT"].append(c)
            continue

        keep_why = None
        if extra_keep is not None and extra_keep.search(phrase):
            keep_why = "case-specific geography / institution from --extra-keep"
        elif KEEP_MARKERS.search(phrase) or ROLE_TAIL.search(phrase):
            keep_why = "institution / office / role / generic phrase"
        elif GEO.search(phrase):
            keep_why = "geography — CLAUDE.md keeps street, city, county"
        elif FORM_LABEL.search(phrase):
            keep_why = "form scaffolding — tokenising a field label corrupts the form"
        elif EPISTOLARY.search(phrase):
            keep_why = "salutation / calendar / event, not a person"
        if keep_why:
            c["decision"] = "KEEP"
            c["_why"] = keep_why
            buckets["KEEP"].append(c)
            continue

        rare = [w for w in words if lower.get(w.lower(), 0) < a.min_lower]
        c["_rare_words"] = rare
        c["_lower_freq"] = {w: lower.get(w.lower(), 0) for w in words}

        if not rare:
            c["decision"] = "KEEP"
            c["_why"] = "every word is attested in lowercase — a phrase, not a name"
            buckets["KEEP"].append(c)
        elif len(words) >= 2 and len(rare) >= 1:
            person_n += 1
            c["decision"] = "CUT"
            c["_why"] = f"proper-noun word(s) never seen in lowercase: {rare}"
            buckets["CUT"].append(c)
        else:
            c["decision"] = "REVIEW"
            c["_why"] = "single rare token — could be a surname or a rare common noun"
            buckets["REVIEW"].append(c)

    # ---- collapse variants onto ONE token per person -------------------------------
    # The first run gave "Firstname Surname", "Recommendation Firstname Surname" and
    # "Firstname Surname Employer" three separate tokens: three identities for one person.
    # That is not a cosmetic flaw. The entire reason for sending the record is to catch a
    # document contradicting another document, and a person split across three identities
    # cannot contradict herself. Tokenisation must be INJECTIVE on people, not on strings.
    #
    # The join key is the phrase's rare words — the proper nouns. All three variants above
    # carry {firstname, surname}; the decorations are common words and drop out. Spelling
    # variants of one surname (a -sky / -ski pair, say) are joined on a shared stem,
    # because a filing spelling a recommender's name two ways is a finding to REPORT, not
    # a reason to invent a second recommender.
    def stem(w: str) -> str:
        w = w.lower().rstrip("'’")
        for suf in ("sky", "ski", "vich", "vych", "ova", "eva", "ыч", "ич"):
            if len(w) > len(suf) + 3 and w.endswith(suf):
                return w[: -len(suf)]
        return w[:-1] if len(w) > 5 else w

    groups: dict[frozenset, list] = collections.defaultdict(list)
    for c in buckets["CUT"]:
        if c.get("_why") == "applicant":
            c["token"] = "[APPLICANT]"
            continue
        key = frozenset(stem(w) for w in c.get("_rare_words", []))
        groups[key].append(c)

    # Subset merge. {firstname, surname} and {firstname, surname, employer} are one person
    # and their firm, and leaving them as two tokens re-opens the split this whole block
    # exists to close. Only merge when the SMALLER key already carries two proper nouns: a
    # bare first name sits inside every full name containing it, and folding it into one of
    # them would invent an identity rather than preserve one.
    keys = sorted(groups, key=len)
    for i, small in enumerate(keys):
        if len(small) < 2 or small not in groups:
            continue
        for big in keys[i + 1:]:
            if big in groups and small < big:
                groups[big].extend(groups.pop(small))
                break

    ordered = sorted(groups.items(),
                     key=lambda kv: (-sum(c["count"] for c in kv[1]),
                                     min(c["phrase"] for c in kv[1])))
    collapsed = 0
    for i, (key, members) in enumerate(ordered, 1):
        tok = f"[PERSON-{i}]"
        if len(members) > 1:
            collapsed += len(members) - 1
        for c in members:
            c["token"] = tok
            c["_variant_of"] = min(members, key=lambda x: len(x["phrase"]))["phrase"]
    print(f"  variants collapsed: {collapsed} phrase(s) folded into "
          f"{len(ordered)} distinct people")

    out = pathlib.Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(
        {"_note": "decisions are heuristic; REVIEW must be settled by hand before apply",
         "candidates": buckets["CUT"] + buckets["REVIEW"] + buckets["KEEP"]},
        ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"  CUT    {len(buckets['CUT']):5}  ({person_n} by the lowercase test, "
          f"{len(buckets['CUT']) - person_n} applicant)")
    print(f"  KEEP   {len(buckets['KEEP']):5}")
    print(f"  REVIEW {len(buckets['REVIEW']):5}  <- settle these by hand")
    print(f"  -> {out}")

    print("\n--- CUT, top 30 by frequency ---")
    for c in sorted(buckets["CUT"], key=lambda x: -x["count"])[:30]:
        print(f"  {c['count']:5}x  {c['phrase'][:44]:44} -> {c['token']:12} {c.get('_rare_words','')}")
    print("\n--- REVIEW, all ---")
    for c in sorted(buckets["REVIEW"], key=lambda x: -x["count"])[:40]:
        print(f"  {c['count']:5}x  {c['phrase'][:44]:44} {c.get('_lower_freq')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
