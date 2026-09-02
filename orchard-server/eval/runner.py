"""Load the dataset, run each scenario through the right driver, grade it."""
from __future__ import annotations

import json
import traceback
from pathlib import Path
from typing import Any

from app.config import Settings

from . import graders, harness, judge

DATASET = Path(__file__).resolve().parent / "dataset.jsonl"


def load_dataset() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for i, line in enumerate(DATASET.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"dataset.jsonl line {i}: {exc}") from exc
    return rows


def _filter(rows: list[dict[str, Any]], *, only: str | None, one_id: str | None) -> list[dict[str, Any]]:
    if one_id:
        return [r for r in rows if r["id"] == one_id]
    if only:
        return [r for r in rows if r["channel"] == only or r["category"] == only]
    return rows


async def _run_row(settings: Settings, row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": row["id"],
        "channel": row["channel"],
        "category": row["category"],
        "exact_fails": [],
        "judge": None,
        "judge_reason": "",
        "error": None,
    }
    try:
        await harness.reset(settings)
        task_ids = await harness.seed(settings, row.get("seed", {}))
        expect = row.get("expect", {})

        if row["channel"] == "chat":
            result = await harness.run_chat(settings, row["messages"])
            out["exact_fails"] = graders.grade_chat(expect, result)
            out["observed"] = {
                "route": result["route"],
                "answer": result["answer"][:600],
                "tools": [c.get("tool") for c in result["tool_calls"]],
                "redirect": bool(result["redirect"]),
            }
            reply_for_judge = result["answer"]
            user_msg = row["messages"][-1]["content"]
        else:
            result = await harness.run_schedule(settings, row, task_ids)
            out["exact_fails"] = graders.grade_schedule(expect, result, task_ids)
            final = result["states"][-1] if result["states"] else None
            out["observed"] = {
                "steps": [s.step for s in result["states"]],
                "proposed": [t.action_type for t in final.proposed_tasks] if final else [],
                "dropped": [t.action_type for t in final.dropped_tasks] if final else [],
                "summary": (final.summary or "")[:400] if final else "",
            }
            reply_for_judge = (final.summary or "") if final else ""
            user_msg = row.get("note", row["id"])

        if row.get("rubric"):
            verdict = await judge.judge(
                settings,
                criterion=row["rubric"],
                user_message=user_msg,
                reply=reply_for_judge,
            )
            out["judge"] = verdict.verdict
            out["judge_reason"] = verdict.reason
    except Exception:  # noqa: BLE001
        out["error"] = traceback.format_exc(limit=4)
    return out


async def run(*, only: str | None = None, one_id: str | None = None) -> dict[str, Any]:
    from . import report

    if not harness.ollama_up():
        raise SystemExit(
            f"Ollama not reachable at {harness.REAL_OLLAMA} - start it "
            "(`ollama serve`) and pull the models first."
        )

    settings = harness.eval_settings()
    await harness.provision()

    rows = _filter(load_dataset(), only=only, one_id=one_id)
    if not rows:
        raise SystemExit("no scenarios matched the filter")

    print(f"running {len(rows)} scenario(s) against {harness.EVAL_DB} + {harness.REAL_OLLAMA}\n")
    results: list[dict[str, Any]] = []
    try:
        for i, row in enumerate(rows, 1):
            print(f"  [{i:>2}/{len(rows)}] {row['id']} ...", flush=True)
            results.append(await _run_row(settings, row))
    finally:
        await harness.teardown()

    text, summary = report.render(results)
    print("\n" + text)
    path = report.save(summary)
    print(f"\nsaved: {path}")
    return summary
