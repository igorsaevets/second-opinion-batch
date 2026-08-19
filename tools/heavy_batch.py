#!/usr/bin/env python3
"""Heavy shared-prefix batch: N adversarial lenses over one large corpus.

Shape of the job. Every item carries the SAME large prefix (system instruction
+ the whole redacted corpus) and differs only in a short trailing lens. That is
the canonical batch shape and it also measures the open question in NOW.md:
whether a cache hit is visible inside a batch, and whether the discount and the
cache stack. The prefix is first in the message list on purpose — implicit
caching keys on a prefix, so a varying preamble would destroy it.

Lanes: OpenRouter `<slug>:batch`. `provider.zdr` is set per request because
OpenRouter's own provider table lists Google AI Studio at 55-day retention and
Google Vertex at zero, and ZDR enforcement is what forces the second.

No third-party dependencies: urllib only, so the paid path has no supply chain.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.request

OR_BASE = "https://openrouter.ai/api/beta/batches"

# --------------------------------------------------------------------------
# The red team. Each lens is one item in the batch.
# Framing is fixed by CLAUDE.md: find the risk AND the lawful cure. Never
# "how to hide it" — an adversarial review that proposes concealment is worse
# than useless, because it is confidently actionable and wrong.
# --------------------------------------------------------------------------
LENSES: list[tuple[str, str]] = [
    ("prong1-merit",
     "Dhanasar prong 1, SUBSTANTIAL MERIT. Attack the claim that the proposed "
     "endeavour has substantial merit. Where is merit asserted rather than shown?"),
    ("prong1-national",
     "Dhanasar prong 1, NATIONAL IMPORTANCE. This is the prong most petitions lose. "
     "Attack the leap from 'this is useful' to 'this has national importance'. "
     "Is the impact shown to extend beyond the petitioner's own employer, clients "
     "and locality?"),
    ("prong2-positioned",
     "Dhanasar prong 2, WELL POSITIONED TO ADVANCE. Attack the record of success, "
     "the progress towards the endeavour, and the interest of relevant parties. "
     "Distinguish plans from achievements."),
    ("prong3-waiver",
     "Dhanasar prong 3, ON BALANCE BENEFICIAL TO WAIVE. Attack the argument that it "
     "would be impractical to require a job offer and labor certification. Note that "
     "prong 3 is NOT 'the applicant is talented' — it is about the waiver itself."),
    ("eb2-threshold",
     "EB-2 THRESHOLD ELIGIBILITY, which is separate from and prior to Dhanasar. "
     "Attack the advanced-degree or exceptional-ability qualification: foreign degree "
     "equivalency, the credential evaluation, the field-to-endeavour nexus."),
    ("endeavor-coherence",
     "ENDEAVOUR DEFINITION. The petition describes more than one line of work. Attack "
     "the coherence: is this one endeavour or several stapled together? Which framing "
     "is strongest, and what does the petitioner lose by keeping the weaker one?"),
    ("evidence-map",
     "EVIDENCE-TO-CLAIM MAPPING. List the load-bearing factual claims that are asserted "
     "with NO exhibit cited, or with an exhibit that cannot support the weight placed "
     "on it. Be specific: quote the claim and name the missing evidence."),
    ("aos-245",
     "ADJUSTMENT OF STATUS ELIGIBILITY under INA 245. Attack lawful admission, "
     "maintenance of status, unauthorised employment, and any 245(c) bar. Scrutinise "
     "the F-1 chronology, the school transfers and every gap between them."),
    ("consular-argument",
     "THE CONSULAR-PROCESSING-UNAVAILABLE ARGUMENT. Attack it on BOTH legs separately: "
     "(a) its legal basis — does unavailability actually matter to the discretionary "
     "analysis? (b) its evidentiary basis — is each factual assertion about the embassy "
     "and the visa suspension actually evidenced and current? Consider third-country "
     "posts."),
    ("discretion",
     "DISCRETION under PM-602-0199. Enumerate the NEGATIVE discretionary factors an "
     "officer could assemble from this record, including ones the petition does not "
     "mention. Then weigh them against the positives the petition offers."),
    ("contradictions",
     "INTERNAL CONTRADICTIONS across the eleven documents. Find dates, numbers, titles, "
     "role descriptions and factual claims that conflict BETWEEN documents. An officer "
     "reads them together. Quote both sides of each conflict and name the two files."),
    ("credibility",
     "CREDIBILITY AND OVERCLAIMING. Read as an officer looking for reasons to doubt. "
     "Find puffery, unverifiable superlatives, statistics without sources, and anything "
     "that would read as inflated. Overclaiming taints the claims that ARE true."),
]

SYSTEM = (
    "You are a senior USCIS adjudications officer at the Nebraska Service Center "
    "conducting an adversarial pre-adjudication review of an EB-2 National Interest "
    "Waiver petition filed concurrently with an I-485 adjustment of status.\n\n"
    "Your job is to find the strongest grounds for a Request for Evidence or a denial, "
    "and then — separately — to state the strongest LAWFUL cure for each. You never "
    "propose concealing, omitting or mischaracterising a fact; a cure is additional "
    "evidence, a better legal framing, or an explanation, never a suppression.\n\n"
    "The record has been redacted: personal identifiers appear as tokens such as "
    "[APPLICANT], [ACADEMIC-RECOMMENDER], [A-NUMBER]. Treat a token as a real, "
    "identified person or number — the redaction is not a gap in the evidence and is "
    "never itself a finding.\n\n"
    "Be concrete and cite the record. A finding that does not quote or name its source "
    "in the record is worthless. Rank by what would actually change the outcome, not by "
    "what is easiest to say."
)

SCHEMA_INSTRUCTION = """
Return ONLY a JSON object, no prose outside it, no markdown fence:

{
  "lens": "<the lens id you were given>",
  "verdict": "<one sentence: would this lens alone support an RFE? a denial? neither?>",
  "findings": [
    {
      "severity": "fatal" | "serious" | "moderate" | "minor",
      "attack": "<the objection in an officer's own voice, 1-3 sentences>",
      "where": "<file name and the quoted words from the record it attacks>",
      "why_it_bites": "<the legal or evidentiary reason this is not merely stylistic>",
      "lawful_cure": "<the strongest lawful fix: what evidence, framing or explanation>",
      "cure_difficulty": "easy" | "moderate" | "hard" | "impossible"
    }
  ],
  "strongest_single_finding": "<the one an officer would actually lead with>",
  "what_the_petition_gets_right_on_this_lens": "<do not flatter; say 'nothing' if so>"
}

Order findings by severity, worst first. Between three and eight findings.
"""


def _lens_pack():
    """Imported lazily and by path: heavy_batch is itself loaded by path from the
    other tools, so a plain `import lens_pack` is not on sys.path at that point."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "lens_pack", pathlib.Path(__file__).resolve().parent / "lens_pack.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore
    return mod


def build_corpus(root: pathlib.Path) -> tuple[str, list[str]]:
    parts, names = [], []
    for p in sorted(root.glob("*.md")):
        names.append(p.name)
        parts.append(f"\n\n===== BEGIN FILE: {p.name} =====\n\n"
                     f"{p.read_text(encoding='utf-8')}"
                     f"\n\n===== END FILE: {p.name} =====\n")
    return "".join(parts), names


def make_requests(corpus: str, lenses: list[tuple[str, str]],
                  guides_dir: "pathlib.Path | None" = None) -> list[dict]:
    """R07: `guides_dir` routes reference material per lens via lens_pack.

    A lens with no route gets NOTHING extra, so the twelve original lenses stay
    byte-identical to R04/R05/R06 and the regression grid keeps its meaning.
    Passing guides_dir=None reproduces the pre-R07 behaviour exactly.
    """
    out = []
    for lens_id, lens_text in lenses:
        msgs = [
            # Prefix first and byte-identical across items: this is what a
            # cache can key on. Anything varying must come after it.
            # (R04 measured cached_tokens: 0 on all 12 items anyway — the shared
            # prefix buys nothing inside a batch. Kept because it costs nothing.)
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": "THE COMPLETE RECORD FOLLOWS.\n" + corpus},
        ]
        if guides_dir is not None:
            block = _lens_pack().build_guide_block(lens_id, guides_dir)
            if block:
                msgs.append({"role": "user", "content": block})
        msgs.append({"role": "user", "content":
                     f"REVIEW LENS — {lens_id}\n\n{lens_text}\n{SCHEMA_INSTRUCTION}"})
        out.append({
            "custom_id": f"lens-{lens_id}",
            "method": "POST",
            "body": {
                "messages": msgs,
                "max_tokens": 16000,
                "reasoning": {"effort": "high"},
                # AI Studio retains 55 days; Vertex retains nothing. ZDR forces Vertex.
                "provider": {"zdr": True},
            },
        })
    return out


def post(url: str, payload: dict, key: str) -> tuple[int, dict]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode()[:4000]}


def get(url: str, key: str) -> tuple[int, dict]:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode()[:4000]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--rundir", required=True)
    ap.add_argument("--model", default="google/gemini-3.7-flash:batch")
    ap.add_argument("--mode", choices=["build", "smoke", "submit", "poll"], required=True)
    ap.add_argument("--tag", default="run")
    ap.add_argument("--lens-set", choices=["base", "extra", "all"], default="base",
                    help="base = the 12 R04 lenses; extra = the 2 R07 coverage "
                         "lenses; all = both")
    ap.add_argument("--lens-only", default="")
    ap.add_argument("--guides", default="",
                    help="directory of REDACTED guides, routed per lens by lens_pack")
    a = ap.parse_args()

    rundir = pathlib.Path(a.rundir)
    rundir.mkdir(parents=True, exist_ok=True)
    corpus, names = build_corpus(pathlib.Path(a.corpus))
    guides_dir = pathlib.Path(a.guides) if a.guides else None

    if a.mode == "build":
        # 3.9 chars/token measured on this corpus family in the R03 smoke; an
        # estimate, and labelled as one. The meter that comes back is the truth.
        est_in = len(corpus) / 3.9
        print(f"files: {len(names)}")
        print(f"corpus chars: {len(corpus):,}")
        print(f"est. input tokens/item: {est_in:,.0f}  (ESTIMATE, not a meter)")
        print(f"lenses: {len(LENSES)}")
        print(f"est. total input tokens: {est_in * len(LENSES):,.0f}")
        print(f"est. input $ @0.1875/M: {est_in * len(LENSES) * 0.1875 / 1e6:.4f}")
        print(f"est. output $ @0.9375/M (8k/item): "
              f"{8000 * len(LENSES) * 0.9375 / 1e6:.4f}")
        (rundir / "corpus.txt").write_text(corpus, encoding="utf-8")
        return 0

    key = os.environ["OPENROUTER_API_KEY"]
    lenses = list(LENSES)
    if a.lens_set == "extra":
        lenses = list(_lens_pack().EXTRA_LENSES)
    elif a.lens_set == "all":
        lenses = lenses + list(_lens_pack().EXTRA_LENSES)
    if a.mode == "smoke":
        lenses = lenses[:1]
    if a.lens_only:
        want = {s.strip() for s in a.lens_only.split(",") if s.strip()}
        lenses = [(i, t) for i, t in lenses if i in want]
    if not lenses:
        print("no lenses selected", file=sys.stderr)
        return 2

    if a.mode in ("smoke", "submit"):
        payload = {
            "endpoint": "/v1/chat/completions",   # NOT /api/v1/... — 400s
            "model": a.model,
            "requests": make_requests(corpus, lenses, guides_dir),
        }
        raw = json.dumps(payload)
        print(f"items: {len(lenses)}   payload bytes: {len(raw):,}")
        status, body = post(OR_BASE, payload, key)
        (rundir / f"{a.tag}.create.json").write_text(
            json.dumps({"status": status, "body": body}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        print(f"HTTP {status}  id={body.get('id')}")
        if status >= 400:
            print(json.dumps(body, indent=2)[:2000])
            return 1
        return 0

    # poll
    created = json.loads((rundir / f"{a.tag}.create.json").read_text(encoding="utf-8"))
    bid = created["body"]["id"]
    status, body = get(f"{OR_BASE}/{bid}", key)
    (rundir / f"{a.tag}.poll.json").write_text(
        json.dumps({"status": status, "body": body}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    st = body.get("status")
    print(f"HTTP {status}  batch status: {st}  counts: {body.get('request_counts')}")
    if st != "completed":
        return 3

    usage = body.get("usage", {})
    print(f"usage: {json.dumps(usage)}")

    parsed, failures = [], []
    for r in body.get("results", []):
        cid = r.get("custom_id")
        try:
            msg = r["response"]["body"]["choices"][0]["message"]["content"]
            u = r["response"]["body"].get("usage", {})
        except (KeyError, IndexError, TypeError):
            failures.append({"custom_id": cid, "raw": str(r)[:600]})
            continue
        txt = re.sub(r"^\s*```(?:json)?|```\s*$", "", msg.strip(), flags=re.M).strip()
        try:
            obj = json.loads(txt)
        except json.JSONDecodeError as e:
            failures.append({"custom_id": cid, "json_error": str(e), "head": txt[:400]})
            continue
        obj["_usage"] = u
        parsed.append(obj)

    (rundir / f"{a.tag}.parsed.json").write_text(
        json.dumps({"parsed": parsed, "failures": failures},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"parsed {len(parsed)} / failed {len(failures)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
