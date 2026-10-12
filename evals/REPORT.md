# SnapKaki — evaluation

Run 2026-10-12 15:03 · `python -m evals.run_eval`

| Measure | Result | |
| --- | --- | --- |
| Gate — irreversible actions stopped | 7/7 (100%) | pass |
| Form match — ours recognised, others not | 5/5 (100%) | pass |
| Accessibility — WCAG AA on the live page | 5/5 (100%) | pass |
| Grounding — in-corpus answered and sourced | 5/5 (100%) | pass |
| Refusal — out-of-corpus declined, not improvised | 4/4 (100%) | pass |
| Cache — repeat scan of the same page | 2/2 (100%) | pass |
| Latency — vision over 5 runs | 5/5 (100%) | pass |

## Latency

- image: 202 KB, downscaled as the client would send it
- p50 **6.2s** · p95 **6.5s** · min 6.0s · max 6.5s over 5 runs

Reading a dense page is the whole cost; everything else is well under a second. See the latency note in docs/architecture.md.

## Cache

- repeat scan of the same page: **9.7s → 0.05s** (179x), and no second model call

No failures.

