# SnapKaki — evaluation

Run 2026-10-13 01:54 · `python -m evals.run_eval`

| Measure | Result | |
| --- | --- | --- |
| Gate — irreversible actions stopped | 7/7 (100%) | pass |
| Form match — ours recognised, others not | 5/5 (100%) | pass |
| Accessibility — WCAG AA on the live page | 5/5 (100%) | pass |
| Grounding — in-corpus answered and sourced | 5/5 (100%) | pass |
| Refusal — out-of-corpus declined, not improvised | 4/4 (100%) | pass |
| Gate live — the real declaration page stops the flow | 3/3 (100%) | pass |
| Languages — answered in the language asked for | 5/5 (100%) | pass |
| Cache — repeat scan of the same page | 2/2 (100%) | pass |
| Latency — vision over 6 runs | 6/6 (100%) | pass |

## Latency

- image: 202 KB, downscaled as the client would send it
- p50 **6.2s** · p95 **6.8s** · min 5.5s · max 6.8s over 6 runs

Reading a dense page is the whole cost; everything else is well under a second. See the latency note in docs/architecture.md.

## Cache

- repeat scan of the same page: **7.3s → 0.06s** (127x), and no second model call

No failures.

