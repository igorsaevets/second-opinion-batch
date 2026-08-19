#!/usr/bin/env python3
"""Recover batch items whose JSON did not parse, without paying for them twice.

MEASURED 2026-08-17: 1 of 12 items (8.3%) emitted invalid JSON despite an
explicit schema in the prompt — a lone backslash before a non-escape character.
At batch scale that is ~83 paid-for-and-lost items per 1000, and a batch cannot
be partially re-run: you would resubmit and pay again.

So repair locally first, and only re-submit what genuinely cannot be read.
Every repair is RECORDED, because a silently repaired payload is a payload
nobody audits.

The repairs are deliberately conservative and syntactic. None of them invents
content; if a repair changes what the model said, that is a bug, not a feature.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re

FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.M)
# A backslash that is not the start of a legal JSON escape.
LONE_BACKSLASH = re.compile(r'\\(?!["\\/bfnrtu])')
TRAILING_COMMA = re.compile(r",(\s*[}\]])")


def repairs(text: str) -> list[tuple[str, str]]:
    """Ordered (name, result) candidates, cheapest and least invasive first."""
    out = [("as-is", text)]
    stripped = FENCE.sub("", text).strip()
    out.append(("strip-fence", stripped))
    out.append(("escape-lone-backslash", LONE_BACKSLASH.sub(r"\\\\", stripped)))
    out.append(("drop-trailing-comma",
                TRAILING_COMMA.sub(r"\1",
                                   LONE_BACKSLASH.sub(r"\\\\", stripped))))
    # Last resort: the outermost {...} span, for prose wrapped around the object.
    i, j = stripped.find("{"), stripped.rfind("}")
    if i != -1 and j > i:
        out.append(("outermost-braces",
                    LONE_BACKSLASH.sub(r"\\\\", stripped[i:j + 1])))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--poll", required=True, help="the <tag>.poll.json from the batch")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    body = json.loads(pathlib.Path(a.poll).read_text(encoding="utf-8"))["body"]
    recovered, still_broken, log = [], [], []

    for r in body.get("results", []):
        cid = r.get("custom_id")
        try:
            msg = r["response"]["body"]["choices"][0]["message"]["content"]
            usage = r["response"]["body"].get("usage", {})
        except (KeyError, IndexError, TypeError):
            still_broken.append({"custom_id": cid, "reason": "no content in response"})
            continue

        for name, candidate in repairs(msg):
            try:
                obj = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            obj["_usage"] = usage
            obj["_repair"] = name
            recovered.append(obj)
            log.append({"custom_id": cid, "repair": name})
            break
        else:
            still_broken.append({"custom_id": cid, "reason": "no repair parsed",
                                 "head": msg[:300]})

    pathlib.Path(a.out).write_text(
        json.dumps({"parsed": recovered, "failures": still_broken},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    by_repair: dict[str, int] = {}
    for e in log:
        by_repair[e["repair"]] = by_repair.get(e["repair"], 0) + 1
    print(f"recovered {len(recovered)} / still broken {len(still_broken)}")
    print(f"repairs used: {by_repair}")
    for e in log:
        if e["repair"] != "as-is":
            print(f"  REPAIRED {e['custom_id']} via {e['repair']}")
    for b in still_broken:
        print(f"  UNRECOVERABLE {b['custom_id']}: {b['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
