# NOW — Batch Review
Updated: 2026-08-16 · single writer: the main session (subagents do not write here)

## Goal
Stand up the project: context/memory scaffold (done), then establish which Batch lanes are
actually reachable and what the two source documents got right and wrong, before any code
is written against a slug or endpoint that does not exist.

## Verified state
| fact | how |
|---|---|
| `D:\Claude Projects` is not inside Yandex.Disk or OneDrive → `.claude/` is safe here (bootstrap P3 = no) | `Get-ChildItem`, roots checked 2026-08-16 |
| `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` absent in User, Machine and process scope | `[Environment]::GetEnvironmentVariable` + `env:` probe, 2026-08-16 |
| `OPENROUTER_API_KEY`, `GEMINI_API_KEY`, `MODEL_API_KEY`, `XAI_API_KEY` present | same probe (presence only, value never printed) |
| `gh` authenticated as `igorsaevets`; git 2.53.0 | `gh auth status`, `git --version` |
| session-anchor hook emits valid JSON, is read-only, makes no network call | dry-run 2026-08-16, output parsed with `ConvertFrom-Json` |
| orchestration default panel is `cheap` since 2026-08-16; 21 channels, 12 in the cheap panel | `python routing.py`, 2026-08-16 |

## Unverified / assumed
- Every factual claim in the two source documents. Nothing from them has been checked yet:
  the OpenRouter batch endpoint path, the `google/gemini-3.7-flash:batch` slug, the 50%
  discount scope per vendor, cache stacking on top of the batch discount, "OpenAI Batch has
  no ZDR", Anthropic batch tool-use/web-search support, Gemini's 20 MB / 2 GB limits.
- Whether OpenAI and Anthropic Batch lanes are wanted at all, given no key exists for either.
- Whether a subscription-billed channel can substitute for a lane with no API key.

## Modified files (current cycle)
`CLAUDE.md`, `.gitignore`, `.claude/settings.json`, `.claude/hooks/session-anchor.ps1`,
`.claude/state/NOW.md`, auto-memory (`MEMORY.md` + topic files).

## Open decisions
1. Repository name and visibility (public vs private) — Igor's call. Nothing pushed yet.
2. Which Batch lanes to fund: OpenAI and Anthropic need keys Igor does not currently have.
3. Whether case material is ever sent to a batch lane at all, or only tokenized derivatives.

## Rejected approaches
- **Copying the other projects' memory files into this store** — rejected: memory is siloed
  per working directory, and a copy is a second home that drifts. One pointer file names
  where each lesson lives instead.
- **A separate `evidence.jsonl`** — rejected: 2/3 external channels rejected it in the
  bootstrap round; a hand-kept ledger reproduces the failure it guards against. Evidence
  lives in this file.
- **Writing the harness first, then verifying slugs** — rejected: the source documents
  contain at least one endpoint and one slug that are probably wrong, and code written
  against them would encode the error.

## Next 3 actions
1. Verify the Batch API claims against live vendor documentation, primary sources only.
2. Snapshot reachable models/slugs/prices to `models_snapshot.json` with a capture date.
3. Run the cheap orchestration panel on the design question and report which channels
   worked, their output token counts, and whether each actually used the internet.

## Evidence
| claim | command | result | date |
|---|---|---|---|
| no cloud sync on project root | `Test-Path` on Yandex.Disk / OneDrive roots + `Get-ChildItem 'D:\Claude Projects'` | project root is outside both | 2026-08-16 |
| two batch lanes have no key | env probe across User/Machine/process | OpenAI, Anthropic = absent | 2026-08-16 |
| hook is safe to wire | dry-run + `ConvertFrom-Json` | valid JSON, no writes, no network | 2026-08-16 |

## Do not assume
- That a model slug printed in a document exists. A slug is a hypothesis until one call returns.
- That "50% cheaper" survives tool fees, search fees, retries and re-validation.
- That a batch can be recalled after submit. It cannot; the smoke test is the only brake.
- That a lane's retention policy matches the vendor's headline privacy claim — search and
  grounding features have carried their own, longer retention.
