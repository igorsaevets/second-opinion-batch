# second-opinion-batch

A harness for running **adversarial document review through Batch APIs** — many independent
blind reviewers over one document set, offline, at roughly half the interactive token price.

Built against a real, high-stakes document set (an immigration filing) and a business-research
workload. The documents themselves are not here and never will be: this repo is
public-by-destination and the publication boundary is enforced in `.gitignore`, not in prose.
What is here is the machinery, and the measurements.

---

## The measurements are the point

Most of what this repo knows was learned by getting something wrong first. Each of these cost
real money or a real wasted round.

**The 50% discount is not Batch's.** Google's Flex tier carries the identical 50% off, is
*synchronous*, and targets 1–15 minutes instead of up to 24 hours. Batch's actual product is
extended rate limits and *guaranteed completion* — Flex is sheddable and was measured shedding
(2 of 12 items returned 503, and one single-item job died after 7 retries). Price is not the
axis on which to choose.

**"24 hours" is a ceiling, not a latency.** Measured: 1 item in 75 s, 12 items in ~4.5 min.
Batch also scales near-flat — 12× the work for 1.25× the wall clock. That, not the discount,
is what it sells.

**An implicit shared prefix buys nothing inside a batch.** A byte-identical 89.7K-token prefix
across 12 items returned `cached_tokens: 0` on every one. Seven of seven external reviewers had
assumed automatic KV-cache reuse.

**Explicit caching does work, and composes with Batch.** `POST /v1beta/cachedContents`, then
reference it as top-level `cachedContent` inside each batch item's `request`. Measured 99.66%
hit across 12 items, payload 4.07 MB → 18.7 KB, cost −59.6%.
🔴 The trap is storage: **$0.50 per 1M tokens per hour.** A ~1M-token cache costs ~$0.49/hour
merely to exist. CREATE → USE → **DELETE**, and delete on the failure path too.

**A fatal-finding count is an instrument reading, not a property of the document.** The same
byte-identical document scored 6 / 8 / 10 across provider and tier combinations. Two runs of the
*identical* configuration scored 8 and 9 with 5 of 12 reviewers reshuffling — so the noise floor
is ±1 and a single-run count is never evidence on its own.

**A PDF form's text layer is the blank template.** `page.get_text()` returns none of what was
typed in; one filed form held **458 filled AcroForm widgets** invisible to it. A corpus built
the obvious way shows the model an empty form, which it then reports as "this section was left
blank" — a false finding manufactured by the pipeline. Use `page.widgets()`.

**`chars / 3.5` is not a token count.** Measured 2.35 ch/tok for OCR output and exhibit tables
against 4.47 for Russian prose — a 1.9× spread, in the opposite direction from the usual
assumption about Cyrillic. `countTokens` is free; use it as the pre-submit gate.

**A unanimous panel can still be wrong.** Thirteen of thirteen external reviewers called one
design element "theatre". A $0.10 ablation ran the same reviewers with and without it and found
the objection was simply false. Argue less, ablate more.

---

## Design rules this enforces

**Money.** A batch is irreversible spend at submit — 1,000 malformed items bill as 1,000 items,
not as one error. So: a 1–2 item smoke test through the same code path precedes every run; the
call plan is written to a file before the first paid call; no auto-retry on a billable error.
Cost is read off the response meter, never off arithmetic on a price list — and where a vendor
returns no meter (Google does not), the figure is labelled *arithmetic* every time it appears.

**Evidence.** `verified` requires a command and its output in the same turn; otherwise the claim
is written as observed / assumed / planned. A search that found nothing means "not confirmed",
never "does not exist". An HTTP 200 is not proof a parameter was applied — judge by a meter that
comes back. Every verdict carries its check method in the text.

**Slugs and prices rot.** Nothing enters the harness except from `models_snapshot.json`, which
carries a capture date and the call that produced it. A model slug is a hypothesis until one
call returns.

**Redaction must be two-sided.** An audit that asks only "did any PII survive?" will report
CLEAN over a wrecked document. One did: it deleted all 83 occurrences of "United States" and 221
of 259 headings, and passed. The audit must also ask "did the document survive?" — and the bug
was found by a *different* method (literal grep plus structural diff), never by a better version
of the same one.

**Tokenisation must be injective on people.** If one person's name variants map to three
different tokens, that person cannot be caught contradicting themselves across documents — which
was the entire reason for assembling the corpus.

---

## Layout

```
tools/          the harness — corpus building, redaction, batch submit/poll, analysis
docs/           vendor behaviour verified against primary sources, with dates
models_snapshot.json   slugs, endpoints, prices, limits — each with the call that captured it
private/  runs/  out/  reviews/   gitignored: source documents, payloads, results
.claude/state/  gitignored: live session state, which by construction accumulates case detail
```

## Requirements

Python 3.11+, `PyMuPDF`, `python-docx`. API keys are read from the environment and are never
printed or logged — not even masked.

## Status

Working research harness, not a product. Interfaces change between rounds.

## Licence

Not yet chosen — treat as all rights reserved until one is added.
