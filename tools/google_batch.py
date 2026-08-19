#!/usr/bin/env python3
"""R07: the REAL Google Batch API — asynchronous `batchGenerateContent`.

NOT the same thing as tools/google_direct_batch.py. That file fires N synchronous
`generateContent` calls in parallel on the Flex service tier. This one submits ONE
asynchronous batch job and polls it. Igor asked for the comparison explicitly
(2026-08-18: "Отправь не Flex, а Batch на google direct и на openrouter, что бы
сравнить"), and the two really are different products:

    Flex   — synchronous, 50% off, target 1-15 min, SHEDDABLE (503 under load;
             R06 lost 2 of 12 items to it and lost a whole diff-eval to it)
    Batch  — asynchronous, 50% off, target 24 h, guaranteed completion,
             extended rate limits

🔴 The 50% is IDENTICAL on both. Price is not the axis of choice and never was;
this project already recorded that (panel-r01). The axis is: sheddable-but-fast
versus guaranteed-but-slow.

Wire shape, from ai.google.dev/gemini-api/docs/batch-api, fetched 2026-08-18:

    POST /v1beta/models/{MODEL}:batchGenerateContent
    {"batch": {"display_name": "...",
               "input_config": {"requests": {"requests": [
                   {"request": {<a GenerateContentRequest>},
                    "metadata": {"key": "<custom id>"}}]}}}}
    -> operation whose name looks like `batches/123456789`

    GET  /v1beta/{BATCH_NAME}      -> poll; state == JOB_STATE_SUCCEEDED
    results for an inline job arrive as `inlinedResponses`

Limits recorded the same day: inline payload < 20 MB; input file < 2 GB; a job
expires after 48 h if still pending.

🟡 WHAT IS NOT VERIFIED HERE. The exact nesting of the poll response's result
array is documented loosely, and `serviceTier` is deliberately NOT sent (Batch is
already the discounted path; stacking a second tier is unprobed and could 400).
Every raw create/poll body is therefore written to disk unmodified, and the
parser walks several plausible locations rather than trusting one. The smoke run
is what turns 🟡 into 🟢 — read `*.poll.json` before believing this docstring.

Reads GEMINI_API_KEY from the environment. NEVER prints or logs the key.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore
    return mod


HB = _load("heavy_batch")
LP = _load("lens_pack")

API = "https://generativelanguage.googleapis.com/v1beta"

# Batch = 50% of standard. gemini-3.7-flash standard: $0.375 in / $1.875 out.
# Captured from the vendor pricing page 2026-08-13; the batch-api page reasserted
# "50% of the standard cost" on 2026-08-18. Arithmetic, not a meter — Google
# returns token counts and no cost field, so this number is only as good as the
# published price. Say so wherever it is reported.
BATCH_IN_PER_M = 0.1875
BATCH_OUT_PER_M = 0.9375
# Explicit-cache read rate, and the storage rate that is the trap. Both captured from
# the vendor pricing page 2026-08-18 and mirrored in models_snapshot.json, which is the
# canonical home — if these two ever disagree, the snapshot wins.
CACHED_IN_PER_M = 0.0375
CACHE_STORAGE_PER_M_PER_HOUR = 0.50
INLINE_CAP_BYTES = 20 * 1024 * 1024


# --------------------------------------------------------------------------
# transport
# --------------------------------------------------------------------------
def _req(url: str, key: str, payload: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(payload).encode() if payload is not None else None
    r = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
        method="POST" if data else "GET",
    )
    try:
        with urllib.request.urlopen(r, timeout=600) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode()[:6000]}
    except urllib.error.URLError as e:
        # R06 lesson: a bare URLError (DNS/socket) used to kill a whole run because
        # only HTTPError was caught. Surface it as a status, never as a traceback.
        return 503, {"error": f"URLError: {str(e.reason)[:300]}"}
    except Exception as e:                                    # noqa: BLE001
        return 500, {"error": f"{type(e).__name__}: {str(e)[:300]}"}


# --------------------------------------------------------------------------
# request construction
# --------------------------------------------------------------------------
def create_cache(corpus: str, model: str, key: str, ttl: str) -> tuple[int, dict]:
    """Explicit context cache over system instruction + the whole record.

    MEASURED 2026-08-18: this DOES compose with batchGenerateContent — every item
    came back with `cachedContentTokenCount` equal to the cached size. That is the
    opposite of the project's implicit-caching result (`cached_tokens: 0` on all 12
    items of an identical-prefix batch), and the two are not in conflict: implicit
    and explicit are different mechanisms.

    🔴 STORAGE BILLS BY THE HOUR ($0.50 per 1M tokens/hour, see models_snapshot.json).
    A 93K-token cache costs ~$0.047/hour to hold. The TTL here is a backstop for a
    failed delete, NOT the plan — the plan is to delete as soon as the batch lands.
    """
    return _req(f"{API}/cachedContents", key, {
        "model": f"models/{model}",
        "displayName": "batch-review-run-cache",
        "systemInstruction": {"parts": [{"text": HB.SYSTEM}]},
        "contents": [{"role": "user",
                      "parts": [{"text": "THE COMPLETE RECORD FOLLOWS.\n" + corpus}]}],
        "ttl": ttl,
    })


def delete_cache(name: str, key: str) -> tuple[int, dict]:
    r = urllib.request.Request(
        f"{API}/{name}", headers={"x-goog-api-key": key}, method="DELETE")
    try:
        with urllib.request.urlopen(r, timeout=120) as resp:
            return resp.status, {}
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode()[:600]}
    except Exception as e:                                     # noqa: BLE001
        return 500, {"error": f"{type(e).__name__}: {str(e)[:200]}"}


def build_inline_requests(corpus: str, lenses: list[tuple[str, str]],
                          guides_dir: pathlib.Path | None,
                          cache_name: str = "") -> list[dict]:
    """With `cache_name`, the system instruction and the record move INTO the cache
    and only the lens tail travels per item — so each request carries ~4 KB instead
    of ~340 KB, and the prefix bills at the cached rate."""
    out = []
    for lens_id, lens_text in lenses:
        guide_block = ""
        if guides_dir is not None:
            guide_block = LP.build_guide_block(lens_id, guides_dir)

        if cache_name:
            parts = []
            if guide_block:
                parts.append({"text": guide_block})
            parts.append({"text": f"REVIEW LENS — {lens_id}\n\n{lens_text}\n"
                                  f"{HB.SCHEMA_INSTRUCTION}"})
            out.append({
                "request": {
                    "cachedContent": cache_name,
                    "contents": [{"role": "user", "parts": parts}],
                    "generationConfig": {
                        "maxOutputTokens": 16000,
                        "thinkingConfig": {"thinkingBudget": 24576,
                                           "includeThoughts": True},
                    },
                    # NOTE: systemInstruction is NOT repeated — it lives in the cache,
                    # and sending it again would be billed uncached.
                },
                "metadata": {"key": f"lens-{lens_id}"},
            })
            continue

        # Order matters and is deliberate: system, then the record, then any
        # reference material, then the lens. The record comes BEFORE the guides
        # so that a lens with guides still reads the petition first — the guides
        # are reference, and reference that displaces the evidence is noise.
        parts = [{"text": "THE COMPLETE RECORD FOLLOWS.\n" + corpus}]
        if guide_block:
            parts.append({"text": guide_block})
        parts.append({"text": f"REVIEW LENS — {lens_id}\n\n{lens_text}\n"
                              f"{HB.SCHEMA_INSTRUCTION}"})

        out.append({
            "request": {
                "systemInstruction": {"parts": [{"text": HB.SYSTEM}]},
                "contents": [{"role": "user", "parts": parts}],
                "generationConfig": {
                    "maxOutputTokens": 16000,
                    "thinkingConfig": {"thinkingBudget": 24576,
                                       "includeThoughts": True},
                },
                # NO serviceTier here: batchGenerateContent IS the discounted
                # path. Stacking `flex` on top is unprobed and could 400 the job
                # — and a 400 on a 12-item batch is 12 items of wasted setup.
            },
            "metadata": {"key": f"lens-{lens_id}"},
        })
    return out


# --------------------------------------------------------------------------
# response parsing
# --------------------------------------------------------------------------
def _find_responses(body: dict) -> list[dict]:
    """Walk the plausible homes of the inline result array.

    The docs name `inlinedResponses` but do not pin its parent, and an operation
    envelope may wrap it in `response` or `metadata`. Rather than assume one and
    silently report zero results, try each and say which one hit.
    """
    for path in (("response", "inlinedResponses", "inlinedResponses"),
                 ("response", "inlinedResponses"),
                 ("inlinedResponses", "inlinedResponses"),
                 ("inlinedResponses",),
                 ("metadata", "inlinedResponses"),
                 ("response", "responses"),
                 ("dest", "inlinedResponses")):
        node = body
        ok = True
        for k in path:
            if isinstance(node, dict) and k in node:
                node = node[k]
            else:
                ok = False
                break
        if ok and isinstance(node, list):
            print(f"  result array found at: {'.'.join(path)}  (n={len(node)})")
            return node
    return []


def parse_results(body: dict) -> tuple[list, list, dict]:
    parsed, failures = [], []
    tot_in = tot_out = tot_th = tot_cached = 0

    for item in _find_responses(body):
        cid = (item.get("metadata") or {}).get("key") or item.get("key") or "?"
        if "error" in item and item.get("error"):
            failures.append({"custom_id": cid, "error": str(item["error"])[:600]})
            continue
        resp = item.get("response") or item
        cands = resp.get("candidates") or []
        if not cands:
            failures.append({"custom_id": cid, "error": "no candidates",
                             "head": json.dumps(resp)[:500]})
            continue
        # thoughts and answer are separate parts when includeThoughts is on
        text = "".join(p.get("text", "")
                       for p in cands[0].get("content", {}).get("parts", [])
                       if not p.get("thought"))
        u = resp.get("usageMetadata", {})
        i, o, th = (u.get("promptTokenCount", 0), u.get("candidatesTokenCount", 0),
                    u.get("thoughtsTokenCount", 0))
        c = u.get("cachedContentTokenCount", 0)
        tot_in += i; tot_out += o; tot_th += th; tot_cached += c

        clean = re.sub(r"^\s*```(?:json)?|```\s*$", "", text.strip(), flags=re.M).strip()
        try:
            obj = json.loads(clean)
        except json.JSONDecodeError as e:
            # R04 measured 8.3% of items returning invalid JSON despite an explicit
            # schema. Keep the text — tools/salvage_json.py runs on it later. A batch
            # cannot be partially re-run, so throwing this away costs a full resubmit.
            failures.append({"custom_id": cid, "json_error": str(e),
                             "head": clean[:400], "raw_text": clean})
            continue
        obj["_usage"] = {"prompt_tokens": i, "completion_tokens": o,
                         "thoughts_tokens": th, "cached_tokens": c}
        parsed.append(obj)

    # Cached prompt tokens bill at the CACHED rate, not the batch input rate. Billing
    # them at BATCH_IN_PER_M overstated a cached 12-lens run by 2.4x on 2026-08-18
    # ($0.279 reported against $0.111 of token cost actually incurred) — a meter that
    # lies high is still a meter that lies.
    # ⚠️ Storage is NOT included here: it is a function of how long the cache is held,
    # which this function cannot see. Add it from the caller. At $0.50 per 1M tokens
    # per hour a 93K cache is ~$0.047/hour, which dwarfs the token saving if held.
    uncached_in = max(0, tot_in - tot_cached)
    cost = (uncached_in * BATCH_IN_PER_M
            + tot_cached * CACHED_IN_PER_M
            + (tot_out + tot_th) * BATCH_OUT_PER_M) / 1e6
    meter = {
        "prompt_tokens": tot_in, "cached_tokens": tot_cached,
        "uncached_prompt_tokens": uncached_in,
        "cache_hit_fraction": round(tot_cached / tot_in, 4) if tot_in else 0.0,
        "completion_tokens": tot_out,
        "thoughts_tokens": tot_th, "cost_arith": round(cost, 6),
        "cost_excludes": "cache STORAGE ($0.50 per 1M tokens per hour) — add per run",
        "rate_in_per_m": BATCH_IN_PER_M, "rate_cached_in_per_m": CACHED_IN_PER_M,
        "rate_out_per_m": BATCH_OUT_PER_M,
        "meter_source": "arithmetic against published Batch price "
                        "(50% of standard; standard captured 2026-08-13, "
                        "50% reasserted on the batch-api page 2026-08-18). "
                        "Google returns NO cost field — this is not a meter.",
        "parsed": len(parsed), "failed": len(failures),
    }
    return parsed, failures, meter


# --------------------------------------------------------------------------
def select_lenses(a: argparse.Namespace) -> list[tuple[str, str]]:
    lenses = list(HB.LENSES)
    if a.lens_set == "extra":
        lenses = list(LP.EXTRA_LENSES)
    elif a.lens_set == "all":
        lenses = lenses + list(LP.EXTRA_LENSES)
    if a.mode == "smoke":
        lenses = lenses[:1]
    if a.lens_only:
        want = {s.strip() for s in a.lens_only.split(",") if s.strip()}
        lenses = [(i, t) for i, t in lenses if i in want]
    return lenses


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--rundir", required=True)
    ap.add_argument("--model", default="gemini-3.7-flash")
    ap.add_argument("--mode", choices=["build", "smoke", "submit", "poll"], required=True)
    ap.add_argument("--tag", default="run")
    ap.add_argument("--lens-set", choices=["base", "extra", "all"], default="base",
                    help="base = the 12 R04 lenses (corpus byte-identical to R06); "
                         "extra = the 2 R07 coverage lenses; all = both")
    ap.add_argument("--lens-only", default="")
    ap.add_argument("--guides", default="",
                    help="directory of REDACTED guides; routed per lens by lens_pack. "
                         "Omit to send no guides at all.")
    ap.add_argument("--use-cache", action="store_true",
                    help="put system instruction + record in an explicit context cache and "
                         "reference it from every item. Cached input bills at $0.0375/M "
                         "against batch input $0.1875/M. STORAGE bills $0.50/M/hour, so the "
                         "cache is deleted as soon as poll reaches a terminal state.")
    ap.add_argument("--cache-ttl", default="3600s",
                    help="backstop only, for the case where the delete itself fails")
    ap.add_argument("--keep-cache", action="store_true",
                    help="do NOT delete the cache on a terminal poll. Costs money by the "
                         "hour; only for chaining several batches over one cache.")
    a = ap.parse_args()

    rundir = pathlib.Path(a.rundir); rundir.mkdir(parents=True, exist_ok=True)
    corpus, names = HB.build_corpus(pathlib.Path(a.corpus))
    guides_dir = pathlib.Path(a.guides) if a.guides else None
    lenses = select_lenses(a)

    if a.mode == "poll":
        key = os.environ["GEMINI_API_KEY"]
        created = json.loads((rundir / f"{a.tag}.create.json").read_text(encoding="utf-8"))
        name = created["body"].get("name") or created["body"].get("batch", {}).get("name")
        if not name:
            print("no batch name in create response — cannot poll")
            return 2
        status, body = _req(f"{API}/{name}", key)
        (rundir / f"{a.tag}.poll.json").write_text(
            json.dumps({"status": status, "body": body}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        state = (body.get("metadata", {}).get("state")
                 or body.get("state") or body.get("done"))
        stats = body.get("metadata", {}).get("batchStats", {})
        print(f"HTTP {status}  state: {state}  stats: {stats}")
        if status >= 400:
            print(json.dumps(body, indent=2)[:1500]); return 1
        # 🔴 MEASURED 2026-08-18 on the R07 smoke: the live API returns
        # `BATCH_STATE_RUNNING`, NOT the `JOB_STATE_RUNNING` the docs summary
        # gave. Checking only for JOB_STATE_SUCCEEDED would never have fired and
        # a finished job would have looked like a hung one forever. Accept both
        # families, and treat any *_FAILED / *_CANCELLED / *_EXPIRED as terminal.
        s = str(state).upper()
        terminal = s.endswith(("_SUCCEEDED", "_FAILED", "_CANCELLED", "_EXPIRED")) \
            or s in ("TRUE", "DONE")

        # Drop the cache ONLY on a terminal state — success or failure alike, because
        # storage bills by the hour either way. Doing it before the still-running check
        # would delete the cache out from under a batch that is still reading it, on
        # every single poll. (Bug caught before it ran, 2026-08-18.)
        cname = created.get("cache_name")
        if terminal and cname and not a.keep_cache:
            dst, _ = delete_cache(cname, key)
            print(f"cache deleted: {cname}  HTTP {dst}")

        if s.endswith(("_FAILED", "_CANCELLED", "_EXPIRED")):
            print(f"TERMINAL FAILURE state: {state}")
            print(json.dumps(body, indent=2)[:2000])
            return 1
        if not terminal:
            return 3
        parsed, failures, meter = parse_results(body)
        (rundir / f"{a.tag}.parsed.json").write_text(
            json.dumps({"parsed": parsed, "failures": failures, "meter": meter},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"parsed {len(parsed)} / failed {len(failures)}")
        print(f"tokens in={meter['prompt_tokens']:,} out={meter['completion_tokens']:,} "
              f"thoughts={meter['thoughts_tokens']:,}")
        print(f"cost_arith: ${meter['cost_arith']:.6f}  (ARITHMETIC, not a meter)")
        for f in failures:
            print(f"  FAIL {f['custom_id']}: {f.get('json_error') or f.get('error','')[:140]}")
        return 0 if not failures else 1

    cache_name = ""
    if a.use_cache and a.mode in ("smoke", "submit"):
        key = os.environ["GEMINI_API_KEY"]
        cst, cbody = create_cache(corpus, a.model, key, a.cache_ttl)
        if cst >= 400:
            print(f"CACHE CREATE FAILED HTTP {cst} — refusing to fall back to an "
                  f"uncached submit, because that would silently bill 10x the input "
                  f"you asked for.")
            print(json.dumps(cbody, indent=2)[:1200])
            return 1
        cache_name = cbody.get("name", "")
        ctok = (cbody.get("usageMetadata") or {}).get("totalTokenCount")
        print(f"cache: {cache_name}  tokens={ctok:,}  ttl={a.cache_ttl}  "
              f"expires={cbody.get('expireTime')}")

    requests_ = build_inline_requests(corpus, lenses, guides_dir, cache_name)
    payload = {"batch": {
        "display_name": f"batch-review-{a.tag}",
        "input_config": {"requests": {"requests": requests_}},
    }}
    raw = json.dumps(payload)
    nbytes = len(raw.encode())

    if a.mode == "build":
        print(f"corpus files: {len(names)}   corpus chars: {len(corpus):,}")
        print(f"lens set: {a.lens_set}   lenses: {len(lenses)}   "
              f"guides: {a.guides or '(none)'}")
        for r in requests_:
            k = r["metadata"]["key"]
            n = sum(len(p["text"]) for p in r["request"]["contents"][0]["parts"])
            print(f"  {k:<26} {n:>9,} chars  ~{n/3.5:>8,.0f} tok (ESTIMATE)")
        est_in = sum(sum(len(p["text"]) for p in r["request"]["contents"][0]["parts"])
                     for r in requests_) / 3.5
        print(f"payload bytes: {nbytes:,}  "
              f"({'OK' if nbytes < INLINE_CAP_BYTES else 'OVER 20MB INLINE CAP'})")
        print(f"est. total input tokens: {est_in:,.0f}  (ESTIMATE, not a meter)")
        print(f"est. input $: {est_in * BATCH_IN_PER_M / 1e6:.4f}")
        print(f"est. output $ @6.5k/item: "
              f"{6500 * len(lenses) * BATCH_OUT_PER_M / 1e6:.4f}")
        (rundir / f"{a.tag}.payload-preview.json").write_text(
            json.dumps({"lenses": [r["metadata"]["key"] for r in requests_],
                        "bytes": nbytes}, indent=2), encoding="utf-8")
        return 0

    if nbytes >= INLINE_CAP_BYTES:
        print(f"REFUSING: payload {nbytes:,} B exceeds the 20 MB inline cap. "
              f"Use the Files API path instead.", file=sys.stderr)
        return 2

    key = os.environ["GEMINI_API_KEY"]
    print(f"items: {len(requests_)}   payload bytes: {nbytes:,}")
    t0 = time.monotonic()
    status, body = _req(f"{API}/models/{a.model}:batchGenerateContent", key, payload)
    (rundir / f"{a.tag}.create.json").write_text(
        json.dumps({"status": status, "body": body,
                    "submit_wall_s": round(time.monotonic() - t0, 2),
                    "items": len(requests_), "payload_bytes": nbytes,
                    # poll reads this to delete the cache once the job is terminal
                    "cache_name": cache_name or None},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    if status >= 400 and cache_name:
        # The submit failed, so no poll will ever run to clean up. Delete now or the
        # cache bills by the hour until its TTL.
        dst, _ = delete_cache(cache_name, os.environ["GEMINI_API_KEY"])
        print(f"submit failed — cache deleted immediately: HTTP {dst}")
    print(f"HTTP {status}  name={body.get('name')}")
    if status >= 400:
        print(json.dumps(body, indent=2)[:2500])
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
