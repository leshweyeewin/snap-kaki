# SnapKaki — evaluation

Run 2026-10-11 21:51 · `python -m evals.run_eval`

| Measure | Result | |
| --- | --- | --- |
| Gate — irreversible actions stopped | 7/7 (100%) | pass |
| Form match — ours recognised, others not | 5/5 (100%) | pass |
| Grounding — in-corpus answered and sourced | 5/5 (100%) | pass |
| Refusal — out-of-corpus declined, not improvised | 4/4 (100%) | pass |
| Latency — vision over 5 runs | 5/5 (100%) | pass |

## Latency

- image: 202 KB, downscaled as the client would send it
- p50 **7.8s** · p95 **9.4s** · min 7.3s · max 9.4s over 5 runs

Reading a dense page is the whole cost; everything else is well under a second. See the latency note in docs/architecture.md.

No failures.

