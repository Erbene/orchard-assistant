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
| `irrigation` | the real water-saving supervisor (`IrrigationSupervisorService.run` + zone solver + Postgres-checkpointed HITL graph) | the proposal's `action`, whether it queued for HITL approval, the solver's run-duration delta / bounds, and the sign of the pre-LLM deficit score |

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
- **Groundedness** (`grounding.py`) — advisory, agronomy chat rows only (see
  below).

## Groundedness (`grounding.py`)

Checks whether an Agronomist answer actually traces back to what was
retrieved, for the 5 `chat-agronomy-*` rows (the only rows that route to
`agronomy` and retrieve anything). Three checks, cheapest first:

1. **Citation validity** — deterministic, no LLM. The Agronomist prompt tells
   the model to cite the source id(s) it used; any cited id that isn't among
   the ids actually retrieved is a **fabricated citation**.
   `chat-agronomy-04-not-covered` exists to catch exactly this.
2. **Claim extraction** — one LLM call breaks the answer into atomic factual
   claims (capped at 8).
3. **Per-claim verification** — one LLM call per claim, run concurrently, each
   scored `supported` / `general_knowledge` / `unsupported` against the
   retrieved context.

`general_knowledge` is a distinct bucket, not a fudge: the Agronomist's system
prompt *explicitly* allows it to answer from its own horticultural knowledge,
ranked below every linked source, as long as it says so —
`chat-agronomy-03-general-knowledge` is designed to be answered this way. A
claim absent from the retrieved context is not automatically a hallucination;
only `unsupported` (absent from context *and* not flagged as general
knowledge) is the real hallucination bucket.

**Advisory only** — printed in the scorecard and saved to the JSON summary,
but not in `report.THRESHOLDS` and does not affect `passed`. With 5 qualifying
rows and a local 7B model grading another local 7B model's claims, this is far
too noisy to gate a run on; a dip is a cue to read the per-claim detail
(`rows[].grounding.claims`) in the saved JSON, the same way a judge dip is a
cue to read the transcript.

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

Irrigation row:

```json
{"id": "irr-01-skip-rain-coming", "channel": "irrigation", "category": "irrigation-skip",
 "seed": {"zone": {"zone_id": "irr-z1", "baseline_minutes": 25},
          "on_date": "2026-06-15",
          "forecast": {"qpf_mm": 25.0},
          "trees": [{"species": "mango", "variety": "Kent", "zone_id": "irr-z1",
                     "canopy_spread_m": 3.0, "estimated_gph": 8.0,
                     "wetted_area_m2": 1.5, "current_vwc": 20.0}]},
 "expect": {"action": "skip_schedule", "hitl": true, "status": "pending",
            "deficit_score_sign": "negative"},
 "rubric": "Explains it is skipping the scheduled irrigation because rain is forecast."}
```

`seed` keys: `trees`, `tasks` (a task may carry `days_old` → sets an overdue
`scheduled_date`), `n_tasks` (N generic tasks named `task 1`…`task N`),
`sources` (`name` + `text`, ingested into the KB).

Irrigation `seed` keys: `zone` (`zone_id` + optional `baseline_minutes` /
`baseline_frequency_days` / `supervised`), `on_date` (`YYYY-MM-DD`, drives the
growth-stage lookup and the forecast date), `trees` (each may carry `zone_id`,
`canopy_spread_m`, `estimated_gph`, `wetted_area_m2`, and `current_vwc` — which
pins a stub moisture sensor for that tree), `forecast` (`{"qpf_mm": N}` or
`{"available": false}`), `rain_bucket_mm` (the 24 h gauge total),
`auto_approve_skips` (bool → supervisor config).

`resumes` entry keys (schedule): `available_minutes`, `have_resources`,
`complete` (action-type names → ids), `report` (free text),
`report_task` (action-type name → `"finished task <id>"`).

`expect` keys — chat: `route` (string or list), `tool` (`null` or
`{name, task_ids}`), `redirect`, `answer_must_mention`,
`answer_must_not_mention`, `answer_nonempty`. schedule: `steps`,
`proposed_action_types`, `not_proposed_action_types`, `dropped_action_types`,
`escalated_action_types`, `warnings_contain`, `summary_present`,
`max_proposed_minutes`, `report_marked`, `db_after.completed_action_types`.
irrigation: `action` (string or list), `status` (string or list), `hitl`
(bool — proposal is a pending approval), `no_proposal` (bool),
`duration_delta` (`negative`/`zero`/`positive` — the solver's run vs baseline),
`recommended_minutes_min` / `recommended_minutes_max`, `deficit_score_sign`
(`negative`/`zero`/`positive` — a deficit of exactly `0.0`, e.g. a tree with no
moisture sensor, is its own `zero` bucket, not coerced into `positive`; a
missing score is graded as an explicit failure, never silently treated as
`0`), `forecast_available` (bool).
