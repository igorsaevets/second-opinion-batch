#!/usr/bin/env python3
"""R06: 12 blind lenses via Google Direct (Gemini generateContent, Flex tier).

Why direct rather than OR batch (R06 pick from Igor 2026-08-18):
    R05 verified OR keeps batch JSONL in GCS for 30 days regardless of ZDR;
    Google Direct's data path is shorter (no reseller). Trade-offs accepted:
      * no `usage.cost` field — arithmetic against the published price is
        the only meter, and its correctness rests on the published price
        not rotting
      * synchronous, not batch — 12 items are fired IN PARALLEL by this
        script rather than submitted as one job to a queue
      * Flex tier is sheddable; a first 503 is expected and retried with
        exponential-plus-jitter backoff (never a metronome, per project rule)

Reads GEMINI_API_KEY from the environment. NEVER prints or logs the key.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import pathlib
import random
import re
import time
import urllib.error
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("heavy_batch", HERE / "heavy_batch.py")
HB = importlib.util.module_from_spec(spec); spec.loader.exec_module(HB)  # type: ignore

# Prices (published, USD per 1M tokens). Rotates — capture date in the file, not memory.
# gemini-3.7-flash: base $0.375 in / $1.875 out; Flex tier is 50% off.
# Captured from vendor page 2026-08-13, R03 smoke matched to 5 digits.
FLEX_IN_PER_M = 0.1875
FLEX_OUT_PER_M = 0.9375


def build_request(system: str, user_a: str, user_b: str) -> dict:
    """Google's generateContent shape. `systemInstruction` is top-level, not a role.
    `serviceTier: "flex"` is what makes this the 50%-off path — a discount tier the
    docs describe as sheddable, so 503 is expected and retried.
    `thinkingConfig.thinkingBudget: 24576` is the model's ceiling for 3.7-flash.
    `includeThoughts: true` puts `thoughtsTokenCount` on the response, so we can
    see the reasoning share R05's OR path hid as `reasoning_tokens: 0`.
    """
    return {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [
            {"role": "user", "parts": [{"text": user_a}]},
            {"role": "user", "parts": [{"text": user_b}]},
        ],
        "generationConfig": {
            "maxOutputTokens": 16000,
            "thinkingConfig": {"thinkingBudget": 24576, "includeThoughts": True},
        },
        "serviceTier": "flex",
    }


async def call_one(session_run_id: str, model: str, key: str, custom_id: str,
                   payload: dict, rundir: pathlib.Path) -> dict:
    """One synchronous generateContent call, retried on 503 with jittered backoff.

    Never a fixed-interval retry: a metronome is a fingerprint (per project rule,
    inherited from ~/.claude/CLAUDE.md). Also cap total attempts at 4.
    """
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = json.dumps(payload).encode()

    def _one() -> tuple[int, dict]:
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json", "x-goog-api-key": key},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, {"error": e.read().decode()[:4000]}
        except urllib.error.URLError as e:
            # DNS / socket / connection reset. Synthetic 503 to trigger retry —
            # this is not a billed vendor failure, so retry is safe.
            return 503, {"error": f"URLError: {str(e.reason)[:200]}"}
        except Exception as e:
            # Any other transport-level failure: synthetic 500, retry once, don't loop.
            return 500, {"error": f"{type(e).__name__}: {str(e)[:200]}"}

    # Longer delays and more attempts than the first round: R06 measured Flex 503
    # surviving 4 attempts / ~18 s of backoff, so try 7 attempts with 11 s cap.
    delays = [2.0, 5.0, 11.0, 11.0, 11.0, 11.0]
    last: tuple[int, dict] = (0, {})
    started = time.monotonic()
    for attempt in range(7):
        loop = asyncio.get_event_loop()
        status, resp = await loop.run_in_executor(None, _one)
        last = (status, resp)
        # Persist EVERY attempt so a killed run does not lose partial evidence.
        (rundir / f"attempt-{custom_id}-{attempt}.json").write_text(
            json.dumps({"status": status, "body": resp}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        if status == 200:
            break
        if status not in (429, 500, 502, 503, 504):
            # Non-retryable: quota exceeded / auth issue / model not found. Stop.
            break
        if attempt < 6:
            base = delays[attempt]
            jitter = random.uniform(0, base * 0.5)
            await asyncio.sleep(min(11.0, base + jitter))
    elapsed = time.monotonic() - started

    return {
        "custom_id": custom_id,
        "status": last[0],
        "body": last[1],
        "elapsed_s": round(elapsed, 2),
    }


def parse_and_cost(results: list[dict]) -> tuple[list[dict], list[dict], dict]:
    parsed, failures = [], []
    tot_in = tot_out = tot_thoughts = 0
    for r in results:
        cid = r["custom_id"]
        if r["status"] != 200:
            failures.append({"custom_id": cid, "status": r["status"],
                             "error": str(r["body"])[:600]})
            continue
        body = r["body"]
        cands = body.get("candidates", [])
        if not cands:
            failures.append({"custom_id": cid, "status": r["status"],
                             "error": "no candidates in response",
                             "head": json.dumps(body)[:600]})
            continue
        parts = cands[0].get("content", {}).get("parts", [])
        # thoughts and text are separate parts when includeThoughts=true.
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        usage = body.get("usageMetadata", {})
        in_tok = usage.get("promptTokenCount", 0)
        out_tok = usage.get("candidatesTokenCount", 0)
        th_tok = usage.get("thoughtsTokenCount", 0)
        # completion total INCLUDES thoughts on this API.
        # Reported "candidatesTokenCount" is answer-only; "thoughtsTokenCount" is thinking.
        tot_in += in_tok; tot_out += out_tok; tot_thoughts += th_tok
        # Conservative JSON parse: strip fences, then json.loads.
        clean = re.sub(r"^\s*```(?:json)?|```\s*$", "", text.strip(), flags=re.M).strip()
        try:
            obj = json.loads(clean)
        except json.JSONDecodeError as e:
            failures.append({"custom_id": cid, "status": 200,
                             "json_error": str(e), "head": clean[:400]})
            continue
        obj["_usage"] = {
            "prompt_tokens": in_tok,
            "completion_tokens": out_tok,
            "thoughts_tokens": th_tok,
            "elapsed_s": r["elapsed_s"],
        }
        parsed.append(obj)

    cost = (tot_in * FLEX_IN_PER_M + (tot_out + tot_thoughts) * FLEX_OUT_PER_M) / 1e6
    meter = {
        "prompt_tokens": tot_in,
        "completion_tokens": tot_out,
        "thoughts_tokens": tot_thoughts,
        "cost_arith": round(cost, 6),
        "rate_in_per_m": FLEX_IN_PER_M,
        "rate_out_per_m": FLEX_OUT_PER_M,
        "meter_source": f"arithmetic against published Flex price (captured 2026-08-13)",
    }
    return parsed, failures, meter


async def main_async(a: argparse.Namespace) -> int:
    rundir = pathlib.Path(a.rundir); rundir.mkdir(parents=True, exist_ok=True)
    key = os.environ["GEMINI_API_KEY"]  # never logged, never printed

    corpus, _ = HB.build_corpus(pathlib.Path(a.corpus))
    lenses = HB.LENSES[:1] if a.mode == "smoke" else HB.LENSES
    if a.lens_only:
        wanted = {s.strip() for s in a.lens_only.split(",") if s.strip()}
        lenses = [(lid, ltext) for lid, ltext in lenses if lid in wanted]
        if not lenses:
            print(f"no lenses matched --lens-only {a.lens_only!r}", file=__import__('sys').stderr)
            return 2
    system = HB.SYSTEM
    schema = HB.SCHEMA_INSTRUCTION

    tasks = []
    for lens_id, lens_text in lenses:
        cid = f"lens-{lens_id}"
        user_a = "THE COMPLETE RECORD FOLLOWS.\n" + corpus
        user_b = f"REVIEW LENS — {lens_id}\n\n{lens_text}\n{schema}"
        payload = build_request(system, user_a, user_b)
        tasks.append(call_one("r06", a.model, key, cid, payload, rundir))

    t0 = time.monotonic()
    # 12 concurrent calls — Google Flex default limits are well above this.
    results = await asyncio.gather(*tasks, return_exceptions=False)
    wall = time.monotonic() - t0

    (rundir / f"{a.tag}.raw.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    parsed, failures, meter = parse_and_cost(results)
    meter["wall_clock_s"] = round(wall, 1)
    meter["item_count"] = len(results)
    meter["parsed"] = len(parsed)
    meter["failed"] = len(failures)

    (rundir / f"{a.tag}.parsed.json").write_text(
        json.dumps({"parsed": parsed, "failures": failures, "meter": meter},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"items: {len(results)}   parsed: {len(parsed)}   failed: {len(failures)}")
    print(f"wall_clock_s: {wall:.1f}")
    print(f"prompt_tokens: {meter['prompt_tokens']:,}   "
          f"completion_tokens: {meter['completion_tokens']:,}   "
          f"thoughts_tokens: {meter['thoughts_tokens']:,}")
    print(f"cost_arith: ${meter['cost_arith']:.6f}")
    for f in failures:
        print(f"  FAIL {f['custom_id']}: status={f.get('status')} "
              f"{f.get('json_error') or f.get('error','')[:120]}")
    return 0 if not failures else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--rundir", required=True)
    ap.add_argument("--model", default="gemini-3.7-flash")
    ap.add_argument("--mode", choices=["smoke", "full"], required=True)
    ap.add_argument("--tag", default="run")
    ap.add_argument("--lens-only", default="",
                    help="comma-separated lens ids to run (subset of the LENSES list); "
                         "for surgical resubmit of failed lenses without paying for the "
                         "10 that already returned.")
    a = ap.parse_args()
    return asyncio.run(main_async(a))


if __name__ == "__main__":
    raise SystemExit(main())
