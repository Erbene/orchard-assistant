# 2026-09-05 role benchmark

Hardware: AMD Ryzen 9 5950X (16 cores / 32 threads), 64 GB RAM, NVIDIA RTX 3070 Ti (8 GB).
Graders stayed on `qwen2.5:7b-instruct` while subject models changed.
`ollama ps` reported `100% GPU` for 7B/8B/4B GPU runs and `100% CPU` for `num_gpu=0` runs.
The 9 GB Qwen2.5 14B weights exceed 8 GB VRAM; later 14B GPU runs still reported `100% GPU`, but that is not treated as proof the model is fully resident.

## CPU thread probe

Warm-up then a second pass of `chat-schedule-01-plan-my-day` with GPU disabled:

| Threads | Warm agent | Probe agent |
| --- | ---: | ---: |
| 16 physical | 26.4 s | 11.5 s |
| 32 logical | 23.0 s | 9.6 s |

32 threads was the faster stable setting and is the CPU profile used below.

## GPU exact matrix

Agent time is subject-model time only (judge/grounding skipped). The first Foreman 7B file (`421.9 s`) is discarded: the graph ignored the override and still ran 14B. The later 7B Foreman run is the valid one.

| Role | Qwen2.5 7B | Qwen2.5 14B | Qwen3 8B | Gemma 3 4B |
| --- | --- | --- | --- | --- |
| Orchestrator (25 chat) | **25/25 · 116 s** | 25/25 · 454 s | 24/25 · 153 s | 23/25 · 136 s |
| Agronomist (6 agronomy) | **6/6 · 50 s** | 6/6 · 718 s | 6/6 · 83 s | 6/6 · 87 s |
| Care-plan fixtures (2) | **2/2 · 59 s** | 2/2 · 748 s | 1/2 · 48 s | 2/2 · 21 s |
| Foreman (12 schedule) | **12/12 · 25 s** | 12/12 · 248 s | 12/12 · 52 s | 12/12 · 26 s |
| Irrigation (12) | **12/12 · 35 s** | 11/12 · 285 s | 10/12 · 185 s | 10/12 · 45 s |

Regressions that blocked a switch:

- Qwen2.5 14B irrigation: `irr-03` chose `adjust_duration` instead of `pass_no_action`.
- Qwen3 8B care-plan: structured JSON parse failure on the mango fixture.
- Qwen3 8B irrigation: `irr-03` and `irr-09` chose the wrong action.
- Gemma 3 4B orchestrator: invented a completion tool call and routed a hide-overdue refusal to `complete`.
- Gemma 3 4B irrigation: `irr-03` and `irr-04` chose the wrong action.

## Quality (fixed 7B judge)

Agronomy chat with judge + grounding enabled:

| Agronomist model | Exact | Judge | Grounded claims | Agent |
| --- | --- | --- | --- | ---: |
| Qwen2.5 7B | 6/6 | **6/6** | 21/22 | 27 s |
| Qwen2.5 14B | 6/6 | 5/6 | 10/10 | 210 s |
| Qwen3 8B | 6/6 | 6/6 | 15/15 | 61 s |
| Gemma 3 4B | 6/6 | 6/6 | 14/14 | 47 s |

14B was slower and did not improve the advisory judge. Qwen3 and Gemma matched 7B on these six agronomy rows but failed exact routing or irrigation suites above, so they were not selected.

Foreman narration is not an exact-check input. 7B, 14B, Qwen3, and Gemma all passed the 12 deterministic schedule rows; 7B wrote usable summaries at 25 s versus 248 s for 14B. The template fallback remains the offline baseline.

## Production assignment

Every live role uses `qwen2.5:7b-instruct`. GPU profile: `OLLAMA_NUM_GPU=999` (`./dev.ps1 -Gpu`). CPU profile: `OLLAMA_NUM_GPU=0` and `OLLAMA_NUM_THREAD=32` (`./dev.ps1 -Cpu`).

| Suite | Exact | Judge | Grounded | Agent | Placement |
| --- | --- | --- | --- | ---: | --- |
| 49-scenario GPU | **49/49** | 29/38 (advisory) | 21/21 | 110 s | `100% GPU` |
| 49-scenario CPU-32 | **49/49** | skipped | skipped | 1177 s | `100% CPU` |

Do not switch a role because a model is larger. Revisit if the dataset adds harder agronomy conflicts, irrigation exact checks regress, or a smaller model matches 49/49 at lower latency.
