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
| 1 | 19 | 181 | 1150 | 3620 | – |
| 4096 | 19 | 171 | 960 | 2161 | – |
| 32768 | 14 | 120 | 534 | 714 | – |

### openai/gpt-oss-20b

| prefix \ N | 1 | 8 | 64 | 256 | prefill (s) |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 54 | 334 | 1615 | 4452 | – |
| 4096 | 47 | 282 | 1593 | 3167 | – |
| 32768 | 26 | 168 | 627 | 995 | – |

vs the 2026-04-25 baseline on 26.03.post1 (git history): single-stream 54
vs 48; N=256/prefix-1 4452 vs 2332 — vLLM 0.22 is a real speedup (different
KV budgets, so not a perfectly controlled comparison).

### Qwen/Qwen3.6-27B-FP8 (partial — slow dense model)

| prefix \ N | 1 | 8 | 64 | 256 | prefill (s) |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 7.9 | 60 | 286 | 386 | – |
| 4096 | 7.6 | 46 | 98 | – | – |
| 32768 | – | – | – | – | – |

~8 tok/s single-stream is bandwidth math: ~29 GB of dense weights per token
on a ~273 GB/s box.

### nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16 (partial)

| prefix \ N | 1 | 8 | 64 | 256 | prefill (s) |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 28 | 143 | 523 | – | – |
| 4096 | 27 | 122 | 188 | – | – |
| 32768 | 19 | 35 | 35 | – | – |

### Qwen/Qwen3.6-35B-A3B-FP8

| prefix \ N | 1 | 8 | 64 | 256 | prefill (s) |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 53 | 271 | 913 | 794 | – |
| 4096 | 49 | 127 | 241 | 93 | – |
| 32768 | 29 | 45 | 30 | – | – |

Inversions at high N with long prefixes = KV-cache pressure → preemption;
for long-context work this model saturates around N=64 on this box.

### google/gemma-4-26B-A4B-it

| prefix \ N | 1 | 8 | 64 | 256 | prefill (s) |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 24 | 178 | 1119 | 3320 | – |
| 4096 | 22 | 187 | 817 | 1411 | – |
| 32768 | 15 | 118 | 486 | 638 | – |

Best long-context scaling of the big models (sliding-window attention).

### Qwen/Qwen3.6-35B-A3B (BF16)

| prefix \ N | 1 | 8 | 64 | 256 | prefill (s) |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 30 | 198 | 619 | – | – |
| 4096 | 29 | 84 | 172 | – | – |
| 32768 | 19 | 32 | 28 | – | – |

FP8 variant is ~1.8× faster single-stream (53 vs 30) — bandwidth-bound, so
prefer FP8 in practice.

### google/gemma-4-31B-it (resharded, partial)

| prefix \ N | 1 | 8 | 64 | 256 | prefill (s) |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 4 | 28 | 152 | – | – |
| 4096 | 4 | 26 | 116 | – | – |
| 32768 | 3 | 19 | 68 | – | – |

Slowest of the fleet, as bandwidth math predicts: ~62 GB of dense BF16
weights per token. Usable interactively only at low concurrency; the
QAT w4a16 variant would be ~4× faster if 31B quality is ever needed at
speed.

### Qwen/Qwen2.5-0.5B-Instruct (not yet benchmarked)

First attempt used 36 000 ctx > its 32 768 native; the requeue was cancelled
when the machine had to shut down. Note its native ctx can't fit the
32 768-prefix row at all.

| prefix \ N | 1 | 8 | 64 | 256 | prefill (s) |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | – | – | – | – | – |
| 4096 | – | – | – | – | – |
| 32768 | n/a | n/a | n/a | n/a | n/a |

### openai/gpt-oss-120b (not yet benchmarked)

Queue stopped at user request before its slot; must run on
`26.03.post1-py3` at `--gpu-memory-utilization 0.60` ([README](./README.md#container-images)).

| prefix \ N | 1 | 8 | 64 | 256 | prefill (s) |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | – | – | – | – | – |
| 4096 | – | – | – | – | – |
| 32768 | – | – | – | – | – |

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
