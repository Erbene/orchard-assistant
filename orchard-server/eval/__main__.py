"""``python -m eval`` entry point."""
from __future__ import annotations

import argparse
import asyncio
import sys

from .runner import run


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m eval", description=__doc__)
    p.add_argument(
        "--only",
        metavar="CHANNEL|CATEGORY",
        help="run only chat, schedule, irrigation, care-plan, or one category",
    )
    p.add_argument("--id", dest="one_id", metavar="SCENARIO_ID", help="run a single scenario by id")
    p.add_argument("--run-label", default="", help="label stored with the result")
    p.add_argument("--profile", choices=("auto", "cpu", "gpu"), default="auto")
    p.add_argument("--num-thread", type=int, help="Ollama CPU inference threads")
    p.add_argument("--num-gpu", type=int, help="Ollama GPU layers (0=CPU, 999=max)")
    p.add_argument("--agent-model", help="Orchestrator subject model")
    p.add_argument("--agronomist-model", help="Agronomist Q&A subject model")
    p.add_argument("--care-plan-model", help="Care-plan extraction subject model")
    p.add_argument("--foreman-model", help="Foreman narration subject model")
    p.add_argument("--irrigation-model", help="Irrigation Supervisor subject model")
    p.add_argument("--judge-model", help="fixed advisory judge model")
    p.add_argument("--grounding-model", help="fixed grounding grader model")
    p.add_argument("--skip-judge", action="store_true", help="skip advisory rubric grading")
    p.add_argument("--skip-grounding", action="store_true", help="skip advisory grounding grading")
    args = p.parse_args()

    if args.num_thread is not None and args.num_thread < 1:
        p.error("--num-thread must be at least 1")
    if args.profile != "auto" and args.num_gpu is not None:
        p.error("use either --profile or --num-gpu, not both")
    num_gpu = args.num_gpu
    if args.profile == "cpu":
        num_gpu = 0
    elif args.profile == "gpu":
        num_gpu = 999

    model_overrides = {
        key: value
        for key, value in {
            "agent_model": args.agent_model,
            "agronomist_model": args.agronomist_model,
            "care_plan_model": args.care_plan_model,
            "foreman_model": args.foreman_model,
            "irrigation_model": args.irrigation_model,
            "judge_model": args.judge_model,
            "grounding_model": args.grounding_model,
        }.items()
        if value
    }
    summary = asyncio.run(
        run(
            only=args.only,
            one_id=args.one_id,
            run_label=args.run_label,
            num_gpu=num_gpu,
            num_thread=args.num_thread,
            model_overrides=model_overrides,
            skip_judge=args.skip_judge,
            skip_grounding=args.skip_grounding,
        )
    )
    sys.exit(0 if summary["passed"] else 1)


if __name__ == "__main__":
    main()
