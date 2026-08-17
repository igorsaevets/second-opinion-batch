# Batch Review — an offline batch-inference factory for legal and business research

Turns questions that would cost a fortune interactively into overnight Batch API jobs at
~50% of live token price: mass claim-verification, adversarial red-teaming, evidence-gap
hunting, and structured idea generation. Two subject domains: **US immigration**
(EB-1, EB-2 NIW, I-485/AOS) and **business-opportunity research** (low-competition,
compliance-moated, unconventional models). Python; destination is a public GitHub repo.

Written in English on purpose: this file ships with the repo.

## Session boot — read in this order
1. `.claude/state/NOW.md` — current goal, verified vs unverified, next actions.
2. `git status` (and `git fetch` only if an upstream exists).
3. Auto-memory topic files, via the index — **open the topic file before the first claim
   on its subject.** MEMORY.md is an index; it is not the evidence.
Read-state does not survive `/compact` or a model switch: re-read a file before Edit.

## Invariants

**Money — this project's whole risk surface is that a typo is a bill.**
- A batch is **irreversible spend at submit**. 1 000 malformed items bill as 1 000 items,
  not as one error. Never submit a batch that has not first run as a **1–2 item smoke test**
  through the same code path.
- Write the **call plan to a file before the first paid call**: lane, model, item count,
  est. input/output tokens, est. cost, ceiling. No auto-retry on a billable error.
- Report **metered cost from the response meter**, never from arithmetic on the price list.
  Two counters over one event that disagree: the one spending money is the wrong one.
- "50% off" is the *token* line only. Tool fees, web-search fees, OCR, retries and
  re-validation are billed on top and have eaten the discount before.

**Evidence.**
- Disk is canonical. A compaction summary is information, not evidence.
- `verified` requires a command and its output **in the same turn**; otherwise write
  observed / assumed / planned. A search that found nothing means "not confirmed",
  never "does not exist".
- A model **produces text, not a citation**, and cannot tell the two apart from inside.
  Every verdict carries its check method in the text: [script: name vs file] /
  [window: file:lines] / [live page: fetched with what] / [channel: who converged].
- An HTTP 200 is not proof a parameter was applied; judge by a meter that comes back.
- Model slugs, endpoints, prices and quotas **rot**. Snapshot them to
  `models_snapshot.json` with a capture date; never hard-code a slug into strategy prose.

**Publication boundary — this repo is public-by-destination.**
- Case material, applicant facts, names, A-/receipt/SEVIS numbers, addresses and any third
  party's name never enter the tree. They live outside it and are referenced by path.
  `private/`, `runs/`, `out/` are gitignored and are where anything case-specific goes.
- PII is tokenized in every payload leaving the project, for every vendor. Cut: full name,
  case numbers, apartment/unit number, phone, email, third-party names. Keep: street, city,
  ZIP, county, institution names — a reviewer cannot verify geography against a token.
- **Verify a lane's retention policy before sending case material to it**, per lane, with a
  date. Retention is a per-vendor, per-feature fact, and grounding/search features have had
  their own longer retention than the base API.
- Secrets are never read, printed or logged — not even masked. Enforcement is
  `.claude/settings.json`; prose forbids nothing.

**Legal and business framing.**
- Model output is not a legal opinion and is never presented as one.
- The correct question is "find the risk and how to neutralise it lawfully with evidence
  or explanation", never "find a way to hide it". Same for business: unconventional and
  low-competition, never unlawful.

## State layer
- `.claude/state/NOW.md` — OVERWRITE, ≤150 lines: goal → verified → unverified → modified
  files → open decisions → rejected approaches (with reason) → next 3 actions → evidence.
- `.claude/state/history/NNN-<topic>.md` — append-only, one file per finished stage.
- Auto-memory holds lessons and durable facts. MEMORY.md ≤200 lines **and** ≤25 KB,
  whichever comes first; Cyrillic is ~2 bytes/char, so bytes bind before lines.
- A new finding corrects the old one **in place** (mark the old SUPERSEDED), never as an
  append at the bottom — compaction resurrects the top of an append-only file.

## Working mode (owner: Igor)
- Autonomous, AI-First: reversible steps without asking; irreversible, outward-facing
  (publish, push, email) and **paid** steps — ask.
- Igor can be wrong; re-check his statements and say so directly.
- Subagents inherit this file but **never** auto-memory: repeat critical rules verbatim in
  the brief. ≤3 parallel agents.
- Every large report ends with "did on my own judgement + rejected alternatives" and a
  "After /compact send me:" block.

## Do not
- Do not rename or move the project root: auto-memory is keyed to the path.
- Do not create a second home for a rule, and do not copy user-level rules here.
- Do not create files "for memory" that nothing loads.
