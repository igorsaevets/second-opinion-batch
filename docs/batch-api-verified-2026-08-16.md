# Batch API mechanics — verified against primary sources, 2026-08-16

Every row below was obtained by opening the vendor's own page (or querying the live API) in the
same session, and is quoted. Where a claim could not be settled it says so. Retrieval date is
**2026-08-16** throughout; these are perishable facts and the date is part of the finding.

Tools used: OpenRouter model API via its MCP server; jina `read_url` for vendor docs (it returns
the page unsummarised — `WebFetch` runs a summariser that has silently dropped enum values before).

---

## 1. Claim ledger

| # | Claim | Verdict | Evidence |
|---|---|---|---|
| C1 | OpenRouter batch is `POST /api/v1/batches` | ❌ **REFUTED** | The path is **`/api/beta/batches`**. Quickstart, verbatim: "Poll for results the same way as any other batch (`GET https://openrouter.ai/api/beta/batches/:id`)." |
| C2 | Slug `google/gemini-3.7-flash:batch` exists | ✅ **CONFIRMED** | Live OpenRouter catalogue returns it: `id: "google/gemini-3.7-flash:batch"`, canonical `google/gemini-3.7-flash-20260813`, 1 048 576 ctx. |
| C3 | 50% off at OpenAI, Google, Anthropic | ✅ **CONFIRMED**, with a large caveat — see §2 | OpenAI: "Each model will be offered at **50% cost discount** vs. the synchronous APIs." Google: "priced at 50% of the standard interactive API cost". Anthropic: "All usage is charged at 50% of the standard API prices." OpenRouter: "typically billed at 50% of the model's standard per-token pricing". |
| C4 | Caching stacks with batch for 75–85% | ⚠️ **MISLEADING — the proposed shape is the one that fails** | See §3. |
| C5 | OpenAI Batch has no ZDR | ✅ **CONFIRMED** verbatim | "If you have zero data retention enabled for your org, please note that **zero data retention does not apply to the Batch API**. ZDR orgs can create batch jobs, but batch input files, outputs, errors, and intermediate artifacts are retained according to the configured Batch, File Service, and Sediment retention policies." |
| C6 | Anthropic batch supports tools incl. web search | ✅ **CONFIRMED**, broader than claimed | "Tool use, including all server tools (**web search, web fetch, code execution, MCP connectors, advisor, and tool search**)", plus **Vision**, multi-turn, **extended thinking**, most beta features. |
| C7 | Gemini batch: 20 MB inline / 2 GB file | ✅ **CONFIRMED** verbatim | "keep the total request size under 20MB"; "The maximum allowed file size for an input file is 2GB." |
| C8 | OpenAI completion window configurable to 7 days | ❌ **REFUTED** (planted control) | "Our current specified time window is 24 hours. **We currently cannot change this time period.**" OpenRouter: "The only supported completion window is `24h`." |
| C9 | Order not guaranteed, `custom_id` required | ✅ **CONFIRMED** | Anthropic: "Use meaningful `custom_id` values to easily match results with requests, **since order is not guaranteed**." |

**Scorecard for the two source documents.** The original note got C1 wrong and C2 right. The
ChatGPT critique got C1 right and **was wrong to cast doubt on C2** — the slug exists. So each
document is wrong about one of the two facts its own code depends on, which is the strongest
available evidence that neither was executed. Neither document states any of §2–§5 below.

---

## 2. What the 50% actually covers — measured, not read

OpenRouter publishes both variants of the same model, so the discount can be **diffed** instead
of trusted. `google/gemini-3.7-flash` vs `google/gemini-3.7-flash:batch`, live catalogue:

| Price line | Sync | Batch | Discount |
|---|---|---|---|
| prompt | $0.375 /M | $0.1875 /M | **−50%** |
| completion | $1.875 /M | $0.9375 /M | **−50%** |
| **internal_reasoning** (thinking) | $1.875 /M | $0.9375 /M | **−50%** |
| input_cache_read | $0.0375 /M | $0.01875 /M | **−50%** |
| **input_cache_write** | $0.0208333 /M | $0.0208333 /M | 🔴 **0% — not discounted** |
| **web_search** | $0.014 /search | $0.014 /search | 🔴 **0% — not discounted** |

Two consequences that change how a batch should be packed:

- 🟢 **Reasoning tokens are discounted.** The single most valuable confirmation here: running a
  Flash model at a high thinking budget overnight is genuinely half price, including the thinking.
  That is the core economic claim of the original note, and it holds.
- 🔴 **Search is billed at full rate and is unit-priced, so it does not scale down with the batch.**
  A batch whose items each run 5 searches pays 5 × $0.014 × N on top, undiscounted. At ~$0.07 of
  search per item, search overtakes the token bill for any item under roughly 190 K input tokens.
  **Grounding, not context, is what makes a batch expensive** — the same finding this machine
  already measured on the live panel (context ≈ free, search ≈ 60% of the bill).

🔴 **`:batch` silently drops four sampling parameters.** Sync supports `temperature`, `top_p`,
`seed`, `stop`; the `:batch` variant's `supported_parameters` omits all four. **A batch run is
therefore not reproducible by seed and not temperature-controlled** on this lane. Nothing in
either source document mentions this, and it matters for any A/B or ensemble design.

---

## 3. The caching claim, and why the proposed design is the failing case

The note proposed: 50 requests in one batch sharing an identical 100 K-token prefix, differing
only in the final question → expect a large cache win on top of the 50%.

That is **exactly the configuration the vendors say does not work.** Verbatim:

- **OpenRouter:** "requests inside a single batch may process concurrently and in any order —
  **a cache written by one line is not guaranteed to be visible to other lines in the same
  batch**."
- **Anthropic:** "because batch requests are processed asynchronously and concurrently, cache
  hits are provided on a **best-effort basis**. Users typically experience cache hit rates
  ranging from 30% to 98%."

And the escape hatch is closed on one lane: Anthropic states **`max_tokens: 0` (cache
pre-warming) is not supported inside a batch**, "because an ephemeral cache entry written during
batch processing would likely expire before the follow-up request runs."

**The working recipe, from OpenRouter's own caching page:** put a `"ttl": "1h"` breakpoint on the
shared prefix and **reuse that prefix across successive batches** — or warm the cache with one
**synchronous** request first. The first batch pays cache-write (which, per §2, is *not*
discounted); later batches read at the halved read rate while the entry stays warm.

So the correct design is **prefix-warm → many sequential batches**, not one big batch. Treat cache
saving as an upside read off `cached_tokens` after the run, never as a budget input.

---

## 4. Constraints that decide the architecture, none of which are in either source document

**OpenRouter Batch**
- 🔴 **Text-only.** "validation rejects any request that carries image, audio, video, or file
  content parts... the Responses `input_image` and `input_file` parts and the Anthropic `image`
  and `document` blocks." → **scanned-PDF / FOIA page triage cannot run on this lane at all.**
- 🔴 **One model per batch.** The batch-level `model` "is applied to every request"; a request
  that sets a different one is rejected. → a cross-model ensemble is N batches, not one.
- 🔴 **On Google models, one `response_format` per batch.** "Google's batch service derives one
  output schema for the whole batch, so requests that disagree fail there." → one batch per schema.
- Results are returned **inline** in the poll response; there is no separate download endpoint.
- Submission returns `202 Accepted` with `status: "validating"` — which is **not** a statement
  that anything succeeded.
- Supported shapes: `/v1/chat/completions`, `/v1/responses`, `/v1/messages`, `/v1/embeddings`.
  All items in one batch share one shape.

**Anthropic Message Batches**
- Limit: **100 000 requests or 256 MB**, whichever comes first.
- Most batches finish in **under 1 hour**; results accessible when all complete **or after 24 h,
  whichever comes first**.
- 🔴 **"batches may go slightly over your Workspace's configured spend limit"** — a configured
  spend cap is *not* a hard stop on this path.
- 🔴 **`pause_turn`**: a tool-use turn can come back unfinished and must be continued in a
  follow-up request. Long web-search items need this handled or they look like truncated answers.
- `web_search` is **throttled per organisation** inside batch, with automatic retry: "very large
  web-search batches might take longer to complete."
- **Vision is supported** — so scanned-document work belongs on this lane, not OpenRouter's.

**Google Gemini Batch**
- Inline under **20 MB**; JSONL input file up to **2 GB**.
- Target 24 h, "in majority of cases much quicker".
- 🔴 **"Submit jobs once"** — batch creation is not idempotent; a retried submit is a second bill.
- On a cache hit "you pay the standard context caching rates".

**OpenAI Batch**
- No cap on request count (embeddings: 1 M enqueued); the real limit is **enqueued input tokens**
  per usage tier.
- **No streaming.**
- 🔴 On expiry, "remaining work is canceled and any already completed work is returned.
  **Developers will be charged for any completed work.**"

---

## 5. What this means for the lane plan

Two of the four lanes have **no API key on this machine** (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`
absent in every scope, probed 2026-08-16). Against the verified facts, that absence is not
symmetric — it removes the only lane that can do two specific things:

| Capability | Only on | Reachable today? |
|---|---|---|
| Scanned pages / vision in batch | Anthropic (and Google file input) | Google ✅, Anthropic ❌ |
| Server-side web search *inside* a batch | Anthropic | ❌ |
| MCP connectors inside a batch | Anthropic | ❌ |
| Discounted reasoning tokens at 1 M context | Google, via OpenRouter `:batch` | ✅ |
| ZDR for case material | **nobody** — OpenAI explicitly excludes Batch | — |

**The honest summary:** the reachable lanes (Google direct, OpenRouter) fully support the
*cheap deep-reasoning* half of the thesis, which is the half that carries the economics. They do
not support the *mass web-grounding inside a batch* half — that is Anthropic-only and needs a key.
Grounding is also the part that is not discounted, so buying it changes the cost model rather
than extending it.
