"""Deterministic checks over a driver result. Fuzzy answer quality is the
judge's job (see ``judge.py``); this module only does exact / structural
matching and cheap substring assertions.

Every check returns a list of failure strings - empty means it passed.
"""
from __future__ import annotations

from typing import Any


def _as_list(v: Any) -> list[Any]:
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def grade_chat(expect: dict[str, Any], result: dict[str, Any]) -> list[str]:
    fails: list[str] = []

    # route (string or list of acceptable routes)
    want_routes = _as_list(expect.get("route"))
    if want_routes and result.get("route") not in want_routes:
        fails.append(f"route={result.get('route')!r}, want one of {want_routes}")

    # tool call
    want_tool = expect.get("tool", "unset")
    if want_tool != "unset":
        calls = result.get("tool_calls", [])
        if want_tool is None:
            if calls:
                fails.append(f"expected no tool call, got {[c.get('tool') for c in calls]}")
        else:
            names = [c.get("tool") for c in calls]
            if want_tool["name"] not in names:
                fails.append(f"tool {want_tool['name']!r} not called (got {names})")
            else:
                call = next(c for c in calls if c.get("tool") == want_tool["name"])
                if "task_ids" in want_tool:
                    got = sorted(int(i) for i in (call.get("args", {}).get("task_ids") or []))
                    if got != sorted(want_tool["task_ids"]):
                        fails.append(
                            f"tool task_ids={got}, want {sorted(want_tool['task_ids'])}"
                        )

    # redirect
    if "redirect" in expect:
        has = bool(result.get("redirect"))
        if has != bool(expect["redirect"]):
            fails.append(f"redirect present={has}, want {bool(expect['redirect'])}")

    fails += _keyword_checks(expect, result.get("answer", ""))
    return fails


def grade_schedule(
    expect: dict[str, Any], result: dict[str, Any], task_ids: dict[str, int]
) -> list[str]:
    fails: list[str] = []
    states = result["states"]

    want_steps = expect.get("steps")
    if want_steps is not None:
        got_steps = [s.step for s in states]
        if got_steps != want_steps:
            fails.append(f"step sequence {got_steps}, want {want_steps}")

    final = states[-1] if states else None

    if final is not None:
        proposed = {t.action_type for t in final.proposed_tasks}
        dropped = {t.action_type for t in final.dropped_tasks}
        escalated = {t.action_type for t in final.proposed_tasks + final.dropped_tasks if t.escalated}

        for a in expect.get("proposed_action_types", []):
            if a not in proposed:
                fails.append(f"{a!r} not in proposed ({sorted(proposed)})")
        for a in expect.get("not_proposed_action_types", []):
            if a in proposed:
                fails.append(f"{a!r} unexpectedly proposed")
        for a in expect.get("dropped_action_types", []):
            if a not in dropped:
                fails.append(f"{a!r} not dropped ({sorted(dropped)})")
        for a in expect.get("escalated_action_types", []):
            if a not in escalated:
                fails.append(f"{a!r} not escalated ({sorted(escalated)})")

        if expect.get("summary_present") and not (final.summary or "").strip():
            fails.append("summary missing")

        for frag in expect.get("warnings_contain", []):
            if not any(frag.lower() in w.lower() for w in final.warnings):
                fails.append(f"no warning contains {frag!r} (got {final.warnings})")

        if "max_proposed_minutes" in expect:
            total = sum(t.estimated_minutes or 0 for t in final.proposed_tasks)
            if total > expect["max_proposed_minutes"]:
                fails.append(f"proposed minutes {total} > {expect['max_proposed_minutes']}")

    # DB side effects
    db_after = expect.get("db_after", {})
    if "completed_action_types" in db_after:
        want = set(db_after["completed_action_types"])
        got = {a for a, s in result["final_status"].items() if s == "completed"}
        if got != want:
            fails.append(f"completed tasks {sorted(got)}, want {sorted(want)}")

    if "report_marked" in expect:
        marked = sorted({i for ids, _ in result["reports"] for i in ids})
        want = sorted(task_ids[a] for a in expect["report_marked"])
        if marked != want:
            fails.append(f"report marked ids {marked}, want {want}")

    return fails


def _keyword_checks(expect: dict[str, Any], answer: str) -> list[str]:
    fails: list[str] = []
    low = answer.lower()
    for kw in expect.get("answer_must_mention", []):
        if kw.lower() not in low:
            fails.append(f"answer missing {kw!r}")
    for kw in expect.get("answer_must_not_mention", []):
        if kw.lower() in low:
            fails.append(f"answer contains forbidden {kw!r}")
    if expect.get("answer_nonempty") and not answer.strip():
        fails.append("answer is empty")
    return fails
