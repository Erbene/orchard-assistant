# Offline evaluation harness

A scored, repeatable check of the assistant's behaviour. **Not** part of
`pytest` — it needs a reachable Ollama and takes several minutes. Run it by
hand before/after a change (a new model, a prompt edit) and compare.

```sh
cd orchard-server
./.venv/Scripts/python -m eval                       # whole dataset
./.venv/Scripts/python -m eval --only chat            # just the chat scenarios
./.venv/Scripts/python -m eval --only schedule
./.venv/Scripts/python -m eval --only refusal         # one category
./.venv/Scripts/python -m eval --id chat-refuse-01-toxic-mix
```

Needs the `postgres` + `chromadb` containers up (`../dev.ps1` or
`docker compose up -d postgres chromadb`) and `ollama serve` with
`qwen2.5:7b-instruct` pulled. Exit code is non-zero when the run is below the
bar (see `report.THRESHOLDS`).

## What it exercises

| channel | driver | graded on |
| --- | --- | --- |
| `chat` | the real Orchestrator graph (`build_graph`) — routing + retrieval + Agronomist | `route`, tool call + args, `redirect`, answer keywords, an AI-judge rubric |
| `schedule` | the real Foreman negotiation (`ForemanService` + Postgres checkpointer) | the `step` sequence across interrupts, which tasks are proposed/dropped/escalated, overdue warnings, and that **no task status changes** until an explicit completion |

Everything runs against a disposable `orchard_eval` database + an
`orchard_knowledge_eval` Chroma collection, truncated between scenarios. Your
real `orchard` data is never touched. The Foreman's narration model
(`qwen2.5:14b`) is optional here — it falls back to the template summary.

## Grading

- **Exact checks** (`graders.py`) — deterministic. These are the hard gate
  (bar: 100%).
- **AI judge** (`judge.py`) — `qwen2.5:7b` scores each free-text answer against
  the row's one-sentence `rubric`. Advisory and a bit noisy; lower bar (85%).
  A judge failure means *look at the transcript*, not necessarily *the code is
  broken*.

## Results

Written to `eval/results/<timestamp>.json` (git-ignored) plus `latest.json`.
Each row records what was observed (`route`, `answer`, `steps`, …) so a
regression is diffable without re-running.

`eval/baselines/` (tracked) holds named snapshots that the main README's
**Model & prompt decisions** log points at — copy a `results/` run there when
it's the evidence behind a decision.

## The dataset (`dataset.jsonl`)

One JSON object per line; `//` lines are comments. It encodes **intended**
behaviour — the first baseline run is expected to surface failures that become
the fix list, not to pass clean.

Chat row:

```json
{"id": "chat-complete-01-two-ids", "channel": "chat", "category": "completion",
 "seed": {"n_tasks": 7},
 "messages": [{"role": "user", "content": "close out tasks 4 and 7, both done"}],
 "expect": {"route": "complete",
            "tool": {"name": "mark_tasks_complete", "task_ids": [4, 7]}},
 "rubric": "Confirms tasks 4 and 7 were marked complete."}
```

Schedule row:

```json
{"id": "sched-03-full-negotiation", "channel": "schedule", "category": "foreman-negotiation",
 "seed": {"tasks": [{"action_type": "copper fungicide spray", "priority_score": 4.0,
                     "estimated_minutes": 30,
                     "required_resources": ["Copper Fungicide", "Sprayer"], "days_old": 15}, ...]},
 "start": {"available_minutes": null},
 "resumes": [{"available_minutes": 90}, {"have_resources": ["Pruning Shears"]}],
 "expect": {"steps": ["need_time", "need_resources", "done"],
            "dropped_action_types": ["copper fungicide spray"],
            "escalated_action_types": ["copper fungicide spray"],
            "warnings_contain": ["overdue"],
            "db_after": {"completed_action_types": []}}}
```

`seed` keys: `trees`, `tasks` (a task may carry `days_old` → sets an overdue
`scheduled_date`), `n_tasks` (N generic tasks named `task 1`…`task N`),
`sources` (`name` + `text`, ingested into the KB).

`resumes` entry keys (schedule): `available_minutes`, `have_resources`,
`complete` (action-type names → ids), `report` (free text),
`report_task` (action-type name → `"finished task <id>"`).

`expect` keys — chat: `route` (string or list), `tool` (`null` or
`{name, task_ids}`), `redirect`, `answer_must_mention`,
`answer_must_not_mention`, `answer_nonempty`. schedule: `steps`,
`proposed_action_types`, `not_proposed_action_types`, `dropped_action_types`,
`escalated_action_types`, `warnings_contain`, `summary_present`,
`max_proposed_minutes`, `report_marked`, `db_after.completed_action_types`.
