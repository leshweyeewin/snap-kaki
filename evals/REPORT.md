# SnapKaki — evaluation

Run 2026-10-11 21:31 · `python -m evals.run_eval`

| Measure | Result | |
| --- | --- | --- |
| Gate — irreversible actions stopped | 7/7 (100%) | pass |
| Form match — ours recognised, others not | 5/5 (100%) | pass |
| Grounding — in-corpus answered and sourced | 4/5 (80%) | FAIL |
| Refusal — out-of-corpus declined, not improvised | 4/4 (100%) | pass |
| Latency — vision over 5 runs | 5/5 (100%) | pass |

## Latency

- image: 202 KB, downscaled as the client would send it
- p50 **20.2s** · p95 **37.6s** · min 13.3s · max 37.6s over 5 runs

Reading a dense page is the whole cost; everything else is well under a second. See the latency note in docs/architecture.md.

## Failures

- **Grounding — in-corpus answered and sourced** — Pink NRIC / Birth Certificate Number: missing any of ['card']
