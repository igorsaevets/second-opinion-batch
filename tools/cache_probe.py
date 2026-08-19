#!/usr/bin/env python3
"""Does EXPLICIT context caching exist, work, and compose with the Batch API?

WHY THIS PROBE EXISTS
Five of the ten cheap-panel channels (2026-08-18) recommended `cachedContent` to cut the
input bill, quoting discounts of 75%, 90% and "10% of standard" — three different numbers,
so none is trusted. This project already MEASURED that a byte-identical 89.7K prefix gave
`cached_tokens: 0` on every item of a 12-item batch — but that was IMPLICIT caching. Explicit
caching is a different mechanism and the measurement does not transfer.

WHAT THE DOCS ACTUALLY GIVE (ai.google.dev/api/caching, read 2026-08-18)
  create  POST   /v1beta/cachedContents        body = a CachedContent
                 required: `model` as "models/{model}"; optional `contents[]`,
                 `systemInstruction`, `displayName`, and expiration as `ttl` ("600s")
                 or `expireTime` (RFC3339). Output has `name` = "cachedContents/{id}"
                 and `usageMetadata.totalTokenCount`.
  list    GET    /v1beta/cachedContents
  get     GET    /v1beta/cachedContents/{id}
  delete  DELETE /v1beta/cachedContents/{id}

WHAT THE DOCS DO NOT GIVE — and is therefore what this probe is for
  1. The FIELD NAME that references a cache from a generateContent request. The guide page
     has been reduced to implicit caching only; it now says explicit caching lives on the
     generateContent API and then shows the same implicit-only text. Candidates tried below.
  2. The PRICE. No storage rate is published anywhere the probe could find. Historically
     this kind of cache bills per token-hour of TTL, so a cache left alive is a meter left
     running. Hence: short TTL AND an unconditional delete in `finally`.
  3. Whether `batchGenerateContent` accepts a cache reference at all. NOT MENTIONED in
     either the caching reference or the batch page. This is the only question that changes
     what this project does, because the batch lane is where the tokens are.

Reads GEMINI_API_KEY from the environment. NEVER prints or logs the key.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
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
API = "https://generativelanguage.googleapis.com/v1beta"


def call(method: str, url: str, key: str, payload: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(payload).encode() if payload is not None else None
    r = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
        method=method,
    )
    try:
        with urllib.request.urlopen(r, timeout=600) as resp:
            body = resp.read().decode()
            return resp.status, (json.loads(body) if body.strip() else {})
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode()[:4000]}
    except urllib.error.URLError as e:
        return 503, {"error": f"URLError: {str(e.reason)[:300]}"}
    except Exception as e:                                     # noqa: BLE001
        return 500, {"error": f"{type(e).__name__}: {str(e)[:300]}"}


def usage_of(body: dict) -> dict:
    u = body.get("usageMetadata", {}) or {}
    return {k: u.get(k) for k in (
        "promptTokenCount", "cachedContentTokenCount", "candidatesTokenCount",
        "thoughtsTokenCount", "totalTokenCount") if u.get(k) is not None}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--rundir", required=True)
    ap.add_argument("--model", default="gemini-3.7-flash")
    ap.add_argument("--ttl", default="600s",
                    help="short on purpose: an undocumented storage price means a cache "
                         "left alive is a meter left running")
    a = ap.parse_args()

    import os
    key = os.environ["GEMINI_API_KEY"]                 # never printed
    rundir = pathlib.Path(a.rundir); rundir.mkdir(parents=True, exist_ok=True)
    corpus, names = HB.build_corpus(pathlib.Path(a.corpus))
    log: dict = {"model": a.model, "ttl": a.ttl, "corpus_chars": len(corpus),
                 "corpus_files": len(names), "steps": []}

    def record(step: str, status: int, body: dict, **extra):
        entry = {"step": step, "status": status, **extra}
        if status >= 400:
            entry["error"] = str(body.get("error"))[:1500]
        log["steps"].append(entry)
        (rundir / "cache-probe.json").write_text(
            json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
        return entry

    cache_name = None
    try:
        # ---- 1. CREATE -----------------------------------------------------
        print(f"corpus: {len(names)} files, {len(corpus):,} chars")
        t0 = time.monotonic()
        status, body = call("POST", f"{API}/cachedContents", key, {
            "model": f"models/{a.model}",
            "displayName": "batch-review-cache-probe",
            "systemInstruction": {"parts": [{"text": HB.SYSTEM}]},
            "contents": [{"role": "user",
                          "parts": [{"text": "THE COMPLETE RECORD FOLLOWS.\n" + corpus}]}],
            "ttl": a.ttl,
        })
        create_s = round(time.monotonic() - t0, 2)
        (rundir / "cache-create.json").write_text(
            json.dumps({"status": status, "body": body}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        if status >= 400:
            record("create", status, body, wall_s=create_s)
            print(f"CREATE FAILED  HTTP {status}")
            print(json.dumps(body, indent=2)[:1800])
            return 1
        cache_name = body.get("name")
        cached_tokens = (body.get("usageMetadata") or {}).get("totalTokenCount")
        record("create", status, body, wall_s=create_s, name=cache_name,
               cached_tokens=cached_tokens, expire_time=body.get("expireTime"))
        print(f"CREATE ok  {cache_name}  cached_tokens={cached_tokens:,}  "
              f"{create_s}s  expires={body.get('expireTime')}")

        lens_id, lens_text = HB.LENSES[0]
        tail = (f"REVIEW LENS — {lens_id}\n\n{lens_text}\n{HB.SCHEMA_INSTRUCTION}")

        # ---- 2. SYNC generateContent referencing the cache ------------------
        # The reference field is undocumented in the guide. `cachedContent` at the top
        # level of GenerateContentRequest is the name the REST resource implies; try it,
        # and if it 400s, report the vendor's own message rather than guessing again.
        t0 = time.monotonic()
        status, body = call(
            "POST", f"{API}/models/{a.model}:generateContent", key,
            {
                "cachedContent": cache_name,
                "contents": [{"role": "user", "parts": [{"text": tail}]}],
                "generationConfig": {"maxOutputTokens": 4000},
            })
        sync_s = round(time.monotonic() - t0, 2)
        (rundir / "cache-sync.json").write_text(
            json.dumps({"status": status, "body": body}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        u = usage_of(body)
        record("sync_generateContent", status, body, wall_s=sync_s, usage=u)
        print(f"SYNC   HTTP {status}  {sync_s}s  usage={u}")
        if status >= 400:
            print("  " + str(body.get("error"))[:700])

        # ---- 3. THE QUESTION: does BATCH accept a cache reference? ----------
        t0 = time.monotonic()
        status, body = call(
            "POST", f"{API}/models/{a.model}:batchGenerateContent", key,
            {"batch": {
                "display_name": "cache-probe-batch",
                "input_config": {"requests": {"requests": [
                    {"request": {
                        "cachedContent": cache_name,
                        "contents": [{"role": "user", "parts": [{"text": tail}]}],
                        "generationConfig": {"maxOutputTokens": 4000},
                    }, "metadata": {"key": "cached-1"}},
                    {"request": {
                        "cachedContent": cache_name,
                        "contents": [{"role": "user", "parts": [{"text": tail}]}],
                        "generationConfig": {"maxOutputTokens": 4000},
                    }, "metadata": {"key": "cached-2"}},
                ]}},
            }})
        batch_s = round(time.monotonic() - t0, 2)
        (rundir / "cache-batch-create.json").write_text(
            json.dumps({"status": status, "body": body}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        record("batch_create_with_cache", status, body, wall_s=batch_s,
               name=body.get("name"))
        print(f"BATCH  HTTP {status}  {batch_s}s  name={body.get('name')}")
        if status >= 400:
            print("  " + str(body.get("error"))[:900])
        else:
            # poll it — a 200 on create is not proof the cache was APPLIED
            bname = body.get("name")
            for i in range(40):
                time.sleep(__import__("random").uniform(4.0, 11.0))
                st, pb = call("GET", f"{API}/{bname}", key)
                state = str((pb.get("metadata") or {}).get("state") or pb.get("state"))
                print(f"  poll {i+1}: {state}")
                if state.endswith(("_SUCCEEDED", "_FAILED", "_CANCELLED", "_EXPIRED")):
                    (rundir / "cache-batch-poll.json").write_text(
                        json.dumps({"status": st, "body": pb}, ensure_ascii=False,
                                   indent=2), encoding="utf-8")
                    ur = []
                    node = ((pb.get("response") or {}).get("inlinedResponses") or {})
                    for it in (node.get("inlinedResponses") or []):
                        ur.append(usage_of(it.get("response") or {}))
                    record("batch_poll", st, pb, state=state, per_item_usage=ur)
                    print(f"  BATCH state={state}  per-item usage: {ur}")
                    break
            else:
                record("batch_poll", 0, {}, state="gave up while running")

        return 0

    finally:
        # ---- 4. ALWAYS DELETE ------------------------------------------------
        # The storage price is undocumented. A cache left alive is a meter left running,
        # and the TTL is only a backstop for the case where this delete itself fails.
        if cache_name:
            st, b = call("DELETE", f"{API}/{cache_name}", key)
            log["steps"].append({"step": "delete", "status": st,
                                 "name": cache_name,
                                 "error": str(b.get("error"))[:400] if st >= 400 else None})
            st2, lb = call("GET", f"{API}/cachedContents", key)
            remaining = [c.get("name") for c in (lb.get("cachedContents") or [])]
            log["steps"].append({"step": "list_after_delete", "status": st2,
                                 "remaining": remaining})
            (rundir / "cache-probe.json").write_text(
                json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"DELETE HTTP {st}   caches still alive after delete: "
                  f"{remaining if remaining else 'none'}")


if __name__ == "__main__":
    raise SystemExit(main())
