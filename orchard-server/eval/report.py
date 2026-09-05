"""Scorecard rendering + JSON persistence for an eval run."""
from __future__ import annotations

import json
import re
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


def render(
    rows: list[dict[str, Any]], *, metadata: dict[str, Any] | None = None
) -> tuple[str, dict[str, Any]]:
    lines: list[str] = []
    lines.append(f"{'id':<26} {'category':<22} {'result':<8} {'agent ms':>10} detail")
    lines.append("-" * 112)

    by_cat: dict[str, list[str]] = defaultdict(list)
    exact_pass = judge_total = judge_pass = 0

    # A2 groundedness (advisory, not in THRESHOLDS - see below).
    claims_total = claims_ok = unsupported_claims = 0
    fabricated_citations = 0
    grounded_rows = 0

    for r in rows:
        st = _status(r)
        by_cat[r["category"]].append(st)
        if not r["exact_fails"] and not r.get("error"):
            exact_pass += 1
        if r.get("judge") in ("pass", "fail"):
            judge_total += 1
            if r["judge"] == "pass":
                judge_pass += 1

        g = r.get("grounding")
        if g and "claims_total" in g:
            grounded_rows += 1
            claims_total += g["claims_total"]
            claims_ok += g["supported"] + g["general_knowledge"]
            unsupported_claims += g["unsupported"]
            fabricated_citations += len(g.get("fabricated_citations") or [])

        detail = ""
        if r.get("error"):
            detail = r["error"][:70]
        elif r["exact_fails"]:
            detail = "; ".join(r["exact_fails"])[:70]
        elif r.get("judge") == "fail":
            detail = f"judge: {r.get('judge_reason', '')}"[:70]
        agent_ms = (r.get("timing_ms") or {}).get("agent", 0.0)
        lines.append(
            f"{r['id']:<26} {r['category']:<22} {st:<8} {agent_ms:>10.1f} {detail}"
        )

    n = len(rows)
    exact_rate = exact_pass / n if n else 0.0
    judge_rate = judge_pass / judge_total if judge_total else 1.0

    lines.append("")
    lines.append("by category:")
    for cat, sts in sorted(by_cat.items()):
        ok = sum(1 for s in sts if s == "pass")
        lines.append(f"  {cat:<24} {ok}/{len(sts)}")

    judge_ok = judge_rate >= THRESHOLDS["judge_rate"]
    # groundedness_rate = (supported + general_knowledge) / claims_total, over
    # the agronomy chat rows only (n=5 in the current dataset). Advisory only:
    # like judge_rate, this is one local 7B model grading another's claims,
    # over too few rows to gate a run on - a dip is a cue to read the
    # per-claim detail in the saved JSON, not a failure signal on its own.
    groundedness_rate = claims_ok / claims_total if claims_total else 1.0
    lines.append("")
    lines.append(f"exact checks : {exact_pass}/{n}  ({exact_rate:.0%})   bar {THRESHOLDS['exact_rate']:.0%}  (gate)")
    lines.append(
        f"judge        : {judge_pass}/{judge_total}  ({judge_rate:.0%})   ref {THRESHOLDS['judge_rate']:.0%}  "
        f"(advisory{'' if judge_ok else ' - below ref, read transcripts'})"
    )
    lines.append(
        f"groundedness : {claims_ok}/{claims_total} claims  ({groundedness_rate:.0%}) over {grounded_rows} "
        f"agronomy row(s)   unsupported={unsupported_claims}  fabricated_citations={fabricated_citations}  "
        "(advisory - n too small + noisy local judge to gate)"
    )
    total_agent_ms = sum((r.get("timing_ms") or {}).get("agent", 0.0) for r in rows)
    total_judge_ms = sum((r.get("timing_ms") or {}).get("judge", 0.0) for r in rows)
    total_grounding_ms = sum(
        (r.get("timing_ms") or {}).get("grounding", 0.0) for r in rows
    )
    lines.append(
        f"timing       : agent={total_agent_ms / 1000:.1f}s  "
        f"judge={total_judge_ms / 1000:.1f}s  "
        f"grounding={total_grounding_ms / 1000:.1f}s"
    )

    passed = exact_rate >= THRESHOLDS["exact_rate"]
    lines.append("")
    lines.append("OVERALL: " + ("PASS" if passed else "BELOW BAR (exact checks)"))

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "metadata": metadata or {},
        "n": n,
        "exact_pass": exact_pass,
        "exact_rate": exact_rate,
        "judge_pass": judge_pass,
        "judge_total": judge_total,
        "judge_rate": judge_rate,
        # Advisory only - not in THRESHOLDS, does not affect `passed`.
        "grounded_rows": grounded_rows,
        "claims_total": claims_total,
        "claims_ok": claims_ok,
        "unsupported_claims": unsupported_claims,
        "fabricated_citations": fabricated_citations,
        "groundedness_rate": groundedness_rate,
        "timing_ms": {
            "agent": round(total_agent_ms, 1),
            "judge": round(total_judge_ms, 1),
            "grounding": round(total_grounding_ms, 1),
            "total": round(
                sum((r.get("timing_ms") or {}).get("total", 0.0) for r in rows),
                1,
            ),
        },
        "passed": passed,
        "rows": rows,
    }
    return "\n".join(lines), summary


def save(summary: dict[str, Any], *, label: str = "") -> Path:
    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_label = re.sub(r"[^a-zA-Z0-9_.-]+", "-", label).strip("-")[:80]
    suffix = f"-{safe_label}" if safe_label else ""
    path = RESULTS_DIR / f"{stamp}{suffix}.json"
    path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    (RESULTS_DIR / "latest.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )
    return path
