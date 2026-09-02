"""Scorecard rendering + JSON persistence for an eval run."""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RESULTS_DIR = Path(__file__).resolve().parent / "results"

# The exact checks are the only hard gate. The judge line is advisory - a
# local model grading another local model's prose is noisy, so a judge dip
# is a cue to read transcripts, not an automatic run failure.
THRESHOLDS = {"exact_rate": 1.0, "judge_rate": 0.85}


def _status(row: dict[str, Any]) -> str:
    if row.get("error"):
        return "ERROR"
    if row["exact_fails"]:
        return "FAIL"
    if row.get("judge") == "fail":
        return "JUDGE?"
    return "pass"


def render(rows: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    lines: list[str] = []
    lines.append(f"{'id':<26} {'category':<22} {'result':<8} detail")
    lines.append("-" * 100)

    by_cat: dict[str, list[str]] = defaultdict(list)
    exact_pass = judge_total = judge_pass = 0

    for r in rows:
        st = _status(r)
        by_cat[r["category"]].append(st)
        if not r["exact_fails"] and not r.get("error"):
            exact_pass += 1
        if r.get("judge") in ("pass", "fail"):
            judge_total += 1
            if r["judge"] == "pass":
                judge_pass += 1

        detail = ""
        if r.get("error"):
            detail = r["error"][:70]
        elif r["exact_fails"]:
            detail = "; ".join(r["exact_fails"])[:70]
        elif r.get("judge") == "fail":
            detail = f"judge: {r.get('judge_reason', '')}"[:70]
        lines.append(f"{r['id']:<26} {r['category']:<22} {st:<8} {detail}")

    n = len(rows)
    exact_rate = exact_pass / n if n else 0.0
    judge_rate = judge_pass / judge_total if judge_total else 1.0

    lines.append("")
    lines.append("by category:")
    for cat, sts in sorted(by_cat.items()):
        ok = sum(1 for s in sts if s == "pass")
        lines.append(f"  {cat:<24} {ok}/{len(sts)}")

    judge_ok = judge_rate >= THRESHOLDS["judge_rate"]
    lines.append("")
    lines.append(f"exact checks : {exact_pass}/{n}  ({exact_rate:.0%})   bar {THRESHOLDS['exact_rate']:.0%}  (gate)")
    lines.append(
        f"judge        : {judge_pass}/{judge_total}  ({judge_rate:.0%})   ref {THRESHOLDS['judge_rate']:.0%}  "
        f"(advisory{'' if judge_ok else ' - below ref, read transcripts'})"
    )

    passed = exact_rate >= THRESHOLDS["exact_rate"]
    lines.append("")
    lines.append("OVERALL: " + ("PASS" if passed else "BELOW BAR (exact checks)"))

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n": n,
        "exact_pass": exact_pass,
        "exact_rate": exact_rate,
        "judge_pass": judge_pass,
        "judge_total": judge_total,
        "judge_rate": judge_rate,
        "passed": passed,
        "rows": rows,
    }
    return "\n".join(lines), summary


def save(summary: dict[str, Any]) -> Path:
    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = RESULTS_DIR / f"{stamp}.json"
    path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    (RESULTS_DIR / "latest.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )
    return path
