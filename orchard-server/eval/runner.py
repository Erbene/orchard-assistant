"""Load the dataset, run each scenario through the right driver, grade it."""
from __future__ import annotations

import json
import os
import platform
import subprocess
import time
import traceback
from pathlib import Path
from typing import Any

from app.config import Settings

from . import graders, grounding, harness, judge

DATASET = Path(__file__).resolve().parent / "dataset.jsonl"
CARE_PLAN_FIXTURES: list[dict[str, Any]] = [
    {
        "id": "care-plan-mango",
        "channel": "care-plan",
        "category": "care-plan",
        "tree": {
            "tree_id": 1,
            "species": "mango",
            "variety": "Kent",
            "height_m": 3.2,
            "canopy_spread_m": 2.8,
        },
        "source_text": (
            "Feed mango lightly in March and May, stopping nitrogen 30 days "
            "before flowering. Scout monthly for scale and anthracnose. Prune "
            "after harvest, mulch before summer, and inspect irrigation monthly. "
            "Typical flowering is February-March, harvest July-August, and the "
            "least active period is December-January."
        ),
        "expected_categories": ["fertilize", "scout", "prune", "mulch", "irrigation"],
        "expected_flowering_months": [2, 3],
        "expected_harvest_months": [7, 8],
    },
    {
        "id": "care-plan-citrus",
        "channel": "care-plan",
        "category": "care-plan",
        "tree": {
            "tree_id": 2,
            "species": "citrus",
            "variety": "Valencia orange",
            "height_m": 2.4,
            "canopy_spread_m": 2.0,
        },
        "source_text": (
            "Fertilize established citrus in February, May, and September. "
            "Scout monthly for leafminer and scale, remove dead wood after "
            "harvest, refresh mulch twice yearly, and check irrigation monthly. "
            "Flowering normally peaks in March and harvest runs March-June."
        ),
        "expected_categories": ["fertilize", "scout", "prune", "mulch", "irrigation"],
        "expected_flowering_months": [3],
        "expected_harvest_months": [3, 4, 5, 6],
    },
]


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


def _hardware_metadata() -> dict[str, Any]:
    physical_cores = None
    memory_gib = None
    try:
        import psutil

        physical_cores = psutil.cpu_count(logical=False)
        memory_gib = round(psutil.virtual_memory().total / (1024**3), 1)
    except ImportError:
        pass
    if os.name == "nt" and (physical_cores is None or memory_gib is None):
        try:
            command = (
                "$p=Get-CimInstance Win32_Processor | Select-Object -First 1;"
                "$c=Get-CimInstance Win32_ComputerSystem;"
                "[pscustomobject]@{cpu=$p.Name;physical_cores=$p.NumberOfCores;"
                "memory_bytes=$c.TotalPhysicalMemory}|ConvertTo-Json -Compress"
            )
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-Command", command],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            win = json.loads(proc.stdout)
            physical_cores = physical_cores or int(win["physical_cores"])
            memory_gib = memory_gib or round(int(win["memory_bytes"]) / (1024**3), 1)
            cpu_name = win["cpu"].strip()
        except (ValueError, KeyError, json.JSONDecodeError, subprocess.SubprocessError):
            cpu_name = platform.processor()
    else:
        cpu_name = platform.processor()
    gpu = None
    try:
        proc = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        gpu = proc.stdout.strip() or None
    except (FileNotFoundError, subprocess.SubprocessError):
        pass
    return {
        "platform": platform.platform(),
        "cpu": cpu_name,
        "physical_cores": physical_cores,
        "logical_threads": os.cpu_count(),
        "memory_gib": memory_gib,
        "gpu": gpu,
    }


def _ollama_ps() -> str:
    try:
        proc = subprocess.run(
            ["ollama", "ps"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return proc.stdout.strip()
    except (FileNotFoundError, subprocess.SubprocessError):
        return ""


async def _run_row(
    settings: Settings,
    row: dict[str, Any],
    *,
    skip_judge: bool,
    skip_grounding: bool,
) -> dict[str, Any]:
    row_started = time.perf_counter()
    out: dict[str, Any] = {
        "id": row["id"],
        "channel": row["channel"],
        "category": row["category"],
        "exact_fails": [],
        "judge": None,
        "judge_reason": "",
        "grounding": None,  # populated for agronomy chat rows only - see below
        "error": None,
        "models": {
            "orchestrator": settings.agent_model,
            "agronomist": settings.agronomist_model,
            "care_plan": settings.care_plan_model,
            "foreman": settings.foreman_model,
            "irrigation": settings.irrigation_model,
            "judge": settings.judge_model,
            "grounding": settings.grounding_model,
        },
        "execution": {
            "num_gpu": settings.ollama_num_gpu,
            "num_thread": settings.ollama_num_thread,
        },
        "timing_ms": {"agent": 0.0, "judge": 0.0, "grounding": 0.0, "total": 0.0},
    }
    try:
        await harness.reset(settings)
        task_ids = await harness.seed(settings, row.get("seed", {}))
        expect = row.get("expect", {})

        if row["channel"] == "care-plan":
            agent_started = time.perf_counter()
            result = await harness.run_care_plan_fixture(
                settings, row["tree"], row["source_text"]
            )
            out["timing_ms"]["agent"] = round(
                (time.perf_counter() - agent_started) * 1000, 1
            )
            templates = result.get("templates") or []
            if not 4 <= len(templates) <= 9:
                out["exact_fails"].append(
                    f"expected 4-9 recurring tasks, got {len(templates)}"
                )
            if any(not t.get("baseline_question") for t in templates):
                out["exact_fails"].append("missing baseline question")
            if any(
                not isinstance(t.get("estimated_minutes"), int)
                or t["estimated_minutes"] <= 0
                for t in templates
            ):
                out["exact_fails"].append("deterministic scaling failed")
            categories = {t.get("category") for t in templates}
            missing_categories = set(row["expected_categories"]) - categories
            if missing_categories:
                out["exact_fails"].append(
                    f"missing source-required categories {sorted(missing_categories)}"
                )
            for calendar in ("flowering_months", "harvest_months"):
                if result.get(calendar) != row[f"expected_{calendar}"]:
                    out["exact_fails"].append(
                        f"{calendar}={result.get(calendar)!r}, "
                        f"want {row[f'expected_{calendar}']!r}"
                    )
            out["observed"] = {
                "task_count": len(templates),
                "categories": [t.get("category") for t in templates],
                "flowering_months": result.get("flowering_months"),
                "harvest_months": result.get("harvest_months"),
            }
            reply_for_judge = json.dumps(out["observed"])
            user_msg = f"Generate a care plan for {row['tree']['species']}"
        elif row["channel"] == "chat":
            agent_started = time.perf_counter()
            result = await harness.run_chat(settings, row["messages"])
            out["timing_ms"]["agent"] = round(
                (time.perf_counter() - agent_started) * 1000, 1
            )
            out["exact_fails"] = graders.grade_chat(expect, result)
            out["observed"] = {
                "route": result["route"],
                "answer": result["answer"][:600],
                "tools": [c.get("tool") for c in result["tool_calls"]],
                "redirect": bool(result["redirect"]),
            }
            reply_for_judge = result["answer"]
            user_msg = row["messages"][-1]["content"]

            # A2 groundedness (advisory - see report.py): only agronomy turns
            # retrieve anything to check claims against. Never let a grading
            # failure here turn the row into an ERROR.
            if (
                not skip_grounding
                and result.get("route") == "agronomy"
                and result.get("retrieved") is not None
            ):
                try:
                    grounding_started = time.perf_counter()
                    out["grounding"] = await grounding.check_groundedness(
                        settings, answer=result["answer"], retrieved=result["retrieved"]
                    )
                    out["timing_ms"]["grounding"] = round(
                        (time.perf_counter() - grounding_started) * 1000, 1
                    )
                except Exception as exc:  # noqa: BLE001
                    out["grounding"] = {"error": str(exc)[:200]}
        elif row["channel"] == "irrigation":
            agent_started = time.perf_counter()
            result = await harness.run_irrigation(settings, row)
            out["timing_ms"]["agent"] = round(
                (time.perf_counter() - agent_started) * 1000, 1
            )
            out["exact_fails"] = graders.grade_irrigation(expect, result)
            prop = result.get("proposal") or {}
            sol = prop.get("solution") or {}
            out["observed"] = {
                "action": (prop.get("decision") or {}).get("action") or prop.get("action"),
                "status": prop.get("status"),
                "deficit_score": prop.get("deficit_score"),
                "recommended_minutes": sol.get("recommended_minutes"),
                "delta_minutes": sol.get("delta_minutes"),
                "summary": (prop.get("summary") or "")[:400],
            }
            reply_for_judge = prop.get("summary") or ""
            user_msg = row.get("note", row["id"])
        else:
            agent_started = time.perf_counter()
            result = await harness.run_schedule(settings, row, task_ids)
            out["timing_ms"]["agent"] = round(
                (time.perf_counter() - agent_started) * 1000, 1
            )
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

        if row.get("rubric") and not skip_judge:
            judge_started = time.perf_counter()
            verdict = await judge.judge(
                settings,
                criterion=row["rubric"],
                user_message=user_msg,
                reply=reply_for_judge,
            )
            out["judge"] = verdict.verdict
            out["judge_reason"] = verdict.reason
            out["timing_ms"]["judge"] = round(
                (time.perf_counter() - judge_started) * 1000, 1
            )
    except Exception:  # noqa: BLE001
        out["error"] = traceback.format_exc(limit=4)
    out["timing_ms"]["total"] = round((time.perf_counter() - row_started) * 1000, 1)
    return out


async def run(
    *,
    only: str | None = None,
    one_id: str | None = None,
    run_label: str = "",
    num_gpu: int | None = None,
    num_thread: int | None = None,
    model_overrides: dict[str, str] | None = None,
    skip_judge: bool = False,
    skip_grounding: bool = False,
) -> dict[str, Any]:
    from . import report

    if not harness.ollama_up():
        raise SystemExit(
            f"Ollama not reachable at {harness.REAL_OLLAMA} - start it "
            "(`ollama serve`) and pull the models first."
        )

    overrides: dict[str, Any] = dict(model_overrides or {})
    if num_gpu is not None:
        overrides["ollama_num_gpu"] = num_gpu
    if num_thread is not None:
        overrides["ollama_num_thread"] = num_thread
    settings = harness.eval_settings(**overrides)
    await harness.provision()

    if only == "care-plan":
        rows = CARE_PLAN_FIXTURES
        if one_id:
            rows = [row for row in rows if row["id"] == one_id]
    else:
        rows = _filter(load_dataset(), only=only, one_id=one_id)
    if not rows:
        raise SystemExit("no scenarios matched the filter")

    print(f"running {len(rows)} scenario(s) against {harness.EVAL_DB} + {harness.REAL_OLLAMA}\n")
    results: list[dict[str, Any]] = []
    try:
        for i, row in enumerate(rows, 1):
            print(f"  [{i:>2}/{len(rows)}] {row['id']} ...", flush=True)
            results.append(
                await _run_row(
                    settings,
                    row,
                    skip_judge=skip_judge,
                    skip_grounding=skip_grounding,
                )
            )
    finally:
        await harness.teardown()

    metadata = {
        "run_label": run_label,
        "filters": {"only": only, "id": one_id},
        "models": {
            "orchestrator": settings.agent_model,
            "agronomist": settings.agronomist_model,
            "care_plan": settings.care_plan_model,
            "foreman": settings.foreman_model,
            "irrigation": settings.irrigation_model,
            "judge": settings.judge_model,
            "grounding": settings.grounding_model,
        },
        "execution": {
            "num_gpu": settings.ollama_num_gpu,
            "num_thread": settings.ollama_num_thread,
            "keep_alive": settings.ollama_keep_alive,
            "skip_judge": skip_judge,
            "skip_grounding": skip_grounding,
        },
        "hardware": _hardware_metadata(),
        "ollama_ps": _ollama_ps(),
    }
    for result in results:
        result["run_label"] = run_label
        result["hardware"] = metadata["hardware"]
    text, summary = report.render(results, metadata=metadata)
    print("\n" + text)
    path = report.save(summary, label=run_label)
    print(f"\nsaved: {path}")
    return summary
