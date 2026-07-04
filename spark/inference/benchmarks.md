# Throughput benchmarks

## Methodology

Harness: [`bench_vllm.py`](./bench_vllm.py) — one consolidated script that
measures prefill latency (cold prefix, `max_tokens=1`, best of 3) plus the
decode-throughput grid. Grid, deadline, context budget, and cell budget are
env-configurable; its docstring has ready-made invocations.

- `/v1/completions` with `prompt` as a raw token-ID array (no tokenizer in
  the loop; prompts/completions are gibberish — that's intentional, and it
  makes the harness model-agnostic).
- Each cell of `(N, prefix_tokens)` sends N concurrent requests that **share
  one random prefix** of length `prefix_tokens`. vLLM's prefix cache absorbs
  the prefill cost after the first request, so each cell measures decode
  throughput at concurrency N (representative of shared-context workloads).
  Caveat: the timed window includes **one** prefill of the shared prefix,
  so low-N long-prefix cells are partly prefill-bound; high-N cells amortize
  it away.
- Output length pinned via `min_tokens=max_tokens` + `ignore_eos=True`.
- Cell value is **total generation throughput (output tok/s)** =
  `sum(completion_tokens) / wall_time` across the cell.
- **prefill (s)** column: measured separately — one request at that prefix
  length, `max_tokens=1`, fresh random prefix (cold cache), best of 3.
  Do NOT derive prefill from N=1 cell walls: decode slows with context, so
  the subtraction wildly overestimates (verified 2026-07-03: derived said
  10.5 s for Qwen3-0.6B @32k, measured 2.46 s).

## 2026-07-03 sweep — all servable models

Setup: `vllm-fixed:26.06` (vLLM 0.22.1), one-off container per model on port
8001, `--max-model-len 36000`, `--gpu-memory-utilization 0.70`, service
stopped. Reduced grid: prefix {1, 4096, 32768} × concurrency {1, 8, 64, 256},
32 768 output tokens per cell (output 64–512 tok/request), ≤30 min per model
(load time excluded), low-concurrency cells first. `–` = not run (per-model
time budget exhausted, or prefill pass not yet done for the big models —
the harness now measures prefill automatically on every future run).
Raw outputs: [bench-results/](./bench-results/).

### Qwen/Qwen3-0.6B

| prefix \ N | 1 | 8 | 64 | 256 | prefill (s) |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 132 | 1108 | 4157 | 12515 | 0.01 |
| 4096 | 103 | 690 | 1545 | 1973 | 0.11 |
| 32768 | 36 | 107 | 245 | 256 | 2.46 |

### google/gemma-4-E2B-it

| prefix \ N | 1 | 8 | 64 | 256 | prefill (s) |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 40 | 363 | 2237 | 6544 | 0.03 |
| 4096 | 38 | 337 | 1883 | 3958 | 0.35 |
| 32768 | 26 | 211 | 1001 | 1200 | 6.12 |

### google/gemma-4-E4B-it

| prefix \ N | 1 | 8 | 64 | 256 | prefill (s) |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 19 | 181 | 1150 | 3620 | 0.06 |
| 4096 | 19 | 171 | 960 | 2161 | 0.61 |
| 32768 | 14 | 120 | 534 | 714 | 7.66 |

### openai/gpt-oss-20b

| prefix \ N | 1 | 8 | 64 | 256 | prefill (s) |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 54 | 334 | 1615 | 4452 | 0.03 |
| 4096 | 47 | 282 | 1593 | 3167 | 0.52 |
| 32768 | 26 | 168 | 627 | 995 | 7.74 |

vs the 2026-04-25 baseline on 26.03.post1 (git history): single-stream 54
vs 48; N=256/prefix-1 4452 vs 2332 — vLLM 0.22 is a real speedup (different
KV budgets, so not a perfectly controlled comparison).

### Qwen/Qwen3.6-27B-FP8

| prefix \ N | 1 | 8 | 64 | 256 | prefill (s) |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 9 | 65 | 299 | 487 | 0.12 |
| 4096 | 8 | 49 | 103 | 35 | 2.03 |
| 32768 | 6 | 16 | 13 | – | 18.77 |

~8 tok/s single-stream is bandwidth math: ~29 GB of dense weights per token
on a ~273 GB/s box. Long-prefix + high-N cells collapse under KV-cache
preemption: (32768, 64) processed 2.1M prompt tokens (every request
re-prefilled) and took 42 min for 12.9 tok/s. The (32768, 256) cell
exceeded a 1-hour per-request timeout on the first attempt; rerun pending
with a 4-hour timeout.

### nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16

| prefix \ N | 1 | 8 | 64 | 256 | prefill (s) |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 29 | 123 | 559 | 707 | 0.04 |
| 4096 | 27 | 124 | 191 | 99 | 0.99 |
| 32768 | 19 | 35 | 36 | 13 | 8.64 |

Same long-prefix inversion as the Qwen MoEs: (32768, 256) collapsed to
13 tok/s under KV preemption (8.4M prompt tokens re-prefilled, 42 min).
Saturates around N=64 for long-context work.

### Qwen/Qwen3.6-35B-A3B-FP8

| prefix \ N | 1 | 8 | 64 | 256 | prefill (s) |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 54 | 252 | 911 | 804 | 0.02 |
| 4096 | 50 | 128 | 242 | 94 | 0.68 |
| 32768 | 29 | 45 | 31 | 14 | 6.49 |

Inversions at high N with long prefixes = KV-cache pressure → preemption;
for long-context work this model saturates around N=64 on this box. The
(32768, 256) cell re-prefilled 8.4M prompt tokens and took 38 min for
14 tok/s.

### google/gemma-4-26B-A4B-it

| prefix \ N | 1 | 8 | 64 | 256 | prefill (s) |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 25 | 169 | 1142 | 3284 | 0.04 |
| 4096 | 24 | 194 | 846 | 1409 | 0.90 |
| 32768 | 15 | 120 | 491 | 630 | 11.14 |

Best long-context scaling of the big models (sliding-window attention).

### Qwen/Qwen3.6-35B-A3B (BF16)

| prefix \ N | 1 | 8 | 64 | 256 | prefill (s) |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 30 | 198 | 619 | – | – |
| 4096 | 29 | 84 | 172 | – | – |
| 32768 | 19 | 32 | 28 | – | – |

FP8 variant is ~1.8× faster single-stream (53 vs 30) — bandwidth-bound, so
prefer FP8 in practice.

### google/gemma-4-31B-it (resharded)

| prefix \ N | 1 | 8 | 64 | 256 | prefill (s) |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 4 | 30 | 124 | 399 | 0.26 |
| 4096 | 4 | 28 | 86 | 169 | 4.21 |
| 32768 | 3 | 20 | 45 | 60 | 50.08 |

Slowest of the fleet, as bandwidth math predicts: ~62 GB of dense BF16
weights per token. Usable interactively only at low concurrency; the
QAT w4a16 variant would be ~4× faster if 31B quality is ever needed at
speed.

### Qwen/Qwen2.5-0.5B-Instruct

Run 2026-07-04 at `--max-model-len 32768` (its native ctx — the
32 768-prefix row can't fit and is n/a).

| prefix \ N | 1 | 8 | 64 | 256 | prefill (s) |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 180 | 1543 | 6464 | 10390 | 0.01 |
| 4096 | 170 | 1397 | 4574 | 6161 | 0.08 |
| 32768 | n/a | n/a | n/a | n/a | n/a |

### openai/gpt-oss-120b

Run 2026-07-04 on `26.03.post1-py3` at `--gpu-memory-utilization 0.60`
(only image that can serve it, [README](./README.md#container-images)).

| prefix \ N | 1 | 8 | 64 | 256 | prefill (s) |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 35 | 225 | 550 | 2861 | 0.03 |
| 4096 | 32 | 138 | 711 | 2155 | 1.00 |
| 32768 | 17 | 111 | 404 | 459 | 13.36 |

Remarkably robust at long context + high concurrency for its size (MoE +
MXFP4: only ~5.1B active params/token; attention sinks keep KV cost low) —
the (32768, 256) cell ran at 459 tok/s where 27B-FP8 timed out outright.

### google/gemma-4-12B-it (cannot serve)

Architecture `gemma4_unified` is unsupported by vLLM 0.22.1
([README](./README.md#models-on-this-box)); no benchmark possible until a newer NGC image.

## Re-running

Reduced grid against a test container: see [`bench_vllm.py`](./bench_vllm.py)'s
docstring. Full grid against the production service:

```sh
VLLM_API_KEY=$(sudo grep ^VLLM_API_KEY /etc/vllm/env | cut -d= -f2) \
BENCH_MODEL=openai/gpt-oss-20b BENCH_MAX_CTX=131072 BENCH_DEADLINE_S=0 \
BENCH_PREFIXES=1,4096,32768,98304 BENCH_CONCURRENCIES=1,4,16,64,256,1024 \
BENCH_CELL_BUDGET=131072 BENCH_OUT_MAX=1024 \
python3 spark/inference/bench_vllm.py
```

Without `VLLM_API_KEY` every request against the service 401s. The
2026-04-25 gpt-oss-20b baseline (26.03.post1) was superseded by the sweep
above; it's in git history if ever needed.
