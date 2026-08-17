# NOW — Batch Review
Updated: 2026-08-16 · single writer: the main session (subagents do not write here)

## Goal
Scaffold is up and the premise has been tested. Next: decide the lane/tier plan with Igor,
then build the smallest harness that can run one real job end to end.

## Verified state
| fact | how |
|---|---|
| `D:\Claude Projects` is not cloud-synced → `.claude/` is safe here | roots checked 2026-08-16 |
| `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` absent in every scope | env probe (presence only) |
| `OPENROUTER_API_KEY`, `GEMINI_API_KEY`, `MODEL_API_KEY`, `XAI_API_KEY` present | same probe |
| 🔴 `GEMINI_API_KEY` is **quota-exhausted** — both Google channels died in <1 s with HTTP 429 | panel round R01, run.log |
| session-anchor hook emits valid JSON, read-only, no network call | dry-run, parsed |
| OpenRouter batch endpoint is `/api/beta/batches` | vendor quickstart, quoted |
| `google/gemini-3.7-flash:batch` exists | live OpenRouter catalogue |
| 🔴 Google **Flex** = same 50% discount as Batch, synchronous, 1–15 min | Google's own comparison table |
| Batch's real advantage = extended rate limits + guaranteed completion | same page |
| Batch halves reasoning tokens; does **not** discount `web_search` or `input_cache_write` | catalogue diff, sync vs `:batch` |
| `:batch` drops `temperature`, `top_p`, `seed`, `stop` | `supported_parameters` diff |
| OpenRouter batch is **text-only**; one model and one `response_format` per batch | vendor quickstart |
| OpenAI Batch has no ZDR; window fixed at 24 h | OpenAI FAQ, quoted |
| Anthropic batch supports web search, MCP, vision, extended thinking; 100 k req / 256 MB | vendor docs, quoted |
| Panel R01: 8/13 channels verified, $2.0582 vendor-reported, 9/9 refuted the planted false claim | run.log |

Full evidence: `docs/batch-api-verified-2026-08-16.md`. Reviews: `private/reviews-r01/`.

## Unverified / assumed
- **Hypothesis:** a cache-heavy Gemini workload may be cheaper via OpenRouter `:batch` (which
  halves `input_cache_read`) than via Google direct (whose page says a cache hit pays "standard
  context caching rates"). Settle by running the same batch on both lanes and diffing cost meters.
- Whether Igor wants to fund OpenAI and/or Anthropic API keys at all.
- Whether the Gemini quota is a spent free tier, a billing lapse, or a rate window — not diagnosed.

## Modified files (current cycle)
`CLAUDE.md`, `.gitignore`, `.claude/settings.json`, `.claude/hooks/session-anchor.ps1`,
`.claude/state/NOW.md`, `docs/batch-api-verified-2026-08-16.md`, auto-memory (5 topic files).

## Open decisions
1. **Repo name + visibility.** Nothing pushed. Local commits are still rewritable (incl. author email).
2. **Fund OpenAI / Anthropic keys?** Anthropic is the only lane that can do web search, MCP and
   vision *inside* a batch. Cost of not having it is concrete; cost of having it is a paid account.
3. **Flex-first or Batch-first?** The verified economics say Flex for most listed workloads.
   This inverts the premise of both source documents and needs Igor's explicit call.
4. Whether case material is ever sent to a lane at all, or only tokenized derivatives — no lane
   offers ZDR on batch.

## Rejected approaches
- Copying other projects' memory files here — memory is siloed; a copy is a second home that drifts.
  One pointer file names where each lesson lives.
- A separate `evidence.jsonl` — evidence lives in this file.
- Writing the harness before verifying slugs — both source docs had a wrong endpoint or slug.
- One large batch with a shared prefix for cache savings — that is the shape vendors say does
  **not** reliably hit cache. Correct shape is prefix-warm + many sequential batches.
- An LLM pass to verify quotations — circular and expensive; mechanical span check first.

## Next 3 actions
1. Put decisions 2 and 3 to Igor; they set the architecture and both cost money.
2. Diagnose the Gemini 429 (spent free tier vs billing vs rate window) — the Google lane is
   currently dead and it is the one lane that is otherwise fully reachable.
3. Build the smallest end-to-end slice: freeze N sources → generate items → **Flex** run →
   mechanical quote check → report. Smoke-test at 1–2 items before any full run.

## Evidence
| claim | command | result | date |
|---|---|---|---|
| two batch lanes have no key | env probe, User/Machine/process | OpenAI, Anthropic absent | 2026-08-16 |
| Google lane quota-exhausted | orchestration round R01 | HTTP 429 on both Google channels | 2026-08-16 |
| batch discount covers reasoning, not search | OpenRouter catalogue diff | reasoning −50%, web_search −0% | 2026-08-16 |
| Flex == Batch price | `ai.google.dev/gemini-api/docs/flex-inference` | vendor comparison table | 2026-08-16 |
| panel does not rubber-stamp | planted claim C8 across 9 answers | 9/9 REFUTED | 2026-08-16 |

## Do not assume
- That "50% off" means Batch. On Google it also means Flex, at 1–15 min instead of 24 h.
- That a key present is a lane reachable — Gemini's key exists and 429s.
- That a slug printed in a document exists, or that an endpoint in one does.
- That a batch can be recalled after submit. The smoke test is the only brake.
- That a "free" model is free — the failed Nemotron run still billed $0.084.
