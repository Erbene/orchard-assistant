# `app/agent` — LangGraph agents

Three **live** LangGraph graphs (not stubs). Prompts, eval numbers, and HTTP
entry points are documented in [orchard-server/README.md](../../README.md).

## 1. Orchestrator — chat router

**Files:** [orchestrator.py](orchestrator.py), [graph.py](graph.py), [state.py](state.py), [agronomist.py](agronomist.py)

```
START → classify → { agronomy | schedule_handoff | complete | refuse | smalltalk } → END
```

One LLM call per turn (`AGENT_MODEL`, structured output) routes the message.
Only the `agronomy` path makes a second call (Chroma retrieval → cited answer).
`schedule_handoff` emits a redirect to `/schedule` — JIT negotiation never
happens in chat. Served over SSE by `ChatService` via `POST /api/v1/chat`.

## 2. Foreman — JIT scheduling

**Files:** [foreman.py](foreman.py), [escalation.py](escalation.py), [checkpointer.py](checkpointer.py)

```
time_check ──(interrupt: need_time)──► propose ──► resource_check
  ──(interrupt: need_resources)──► finalize ──► narrate ──► END
```

Checkpointed Postgres graph with two interrupts (`need_time` / `need_resources`).
Deterministic Python (`escalation` → knapsack pack → resource check → refit) —
no node writes the DB until `/complete` or `/report`. Optional Ollama narration
(`FOREMAN_MODEL`). Driven over REST at `/api/v1/schedule/*`.

## 3. Irrigation supervisor — HITL + ToT zone solver

**Files:** [irrigation_supervisor.py](irrigation_supervisor.py), [zone_solver.py](zone_solver.py)

```
START → deliberate → contention → summarize → execute_rachio_action → END
                                                    ▲ interrupt_before (HITL)
```

`deliberate` picks one of four actions; `contention` runs the ToT beam-search
solver for zone duration; `summarize` writes grower-facing prose. **Every action
including `pass_no_action` goes through summarize and pauses at
`interrupt_before=["execute_rachio_action"]`** — there is no pass short-circuit
to END. Actuation is currently `dry_run`. A Python guard after the graph enforces
the 2-day spacing rule from Rachio `lastWateredDate`.

## Supporting modules (pure Python, no graph)

| File | Role |
| ---- | ---- |
| [care_plan.py](care_plan.py) | Canopy-volume scaler for care-plan templates |
| [schedule_solver.py](schedule_solver.py) | Biological calendar dates (`valid_months`, anchors, phenology) |
| [ollama.py](ollama.py) | Shared `chat_model()` helper (num_gpu / num_thread / keep_alive) |
| [client.py](client.py) | MCP tool binding for agent clients |

RAG is Chroma retrieval with `priority_order` source headers — not four-tier
fusion. CrewAI is not used anywhere in this tree.
