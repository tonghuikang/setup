# Throughput benchmarks

## Methodology

Harness: [`bench_vllm.py`](./bench_vllm.py) (full grid, used 2026-04-25) and a
reduced-grid variant of it (2026-07-03 sweep, all models).

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

## 2026-07-03 sweep — all servable models

Setup: `vllm-fixed:26.06` (vLLM 0.22.1), one-off container per model on port
8001, `--max-model-len 36000`, `--gpu-memory-utilization 0.70`, service
stopped. Reduced grid: prefix {1, 4096, 32768} × concurrency {1, 8, 64, 256},
32 768 output tokens per cell (output 64–512 tok/request), ≤30 min per model
(load time excluded), low-concurrency cells first. `–` = cell not run
(per-model time budget exhausted; slow models can't finish the heavy cells
by construction). Raw outputs: [bench-results/](./bench-results/).

### Qwen/Qwen3-0.6B

| prefix \ N | 1 | 8 | 64 | 256 |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 132 | 1108 | 4157 | 12515 |
| 4096 | 103 | 690 | 1545 | 1973 |
| 32768 | 36 | 107 | 245 | 256 |

### google/gemma-4-E2B-it

| prefix \ N | 1 | 8 | 64 | 256 |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 40 | 363 | 2237 | 6544 |
| 4096 | 38 | 337 | 1883 | 3958 |
| 32768 | 26 | 211 | 1001 | 1200 |

### google/gemma-4-E4B-it

| prefix \ N | 1 | 8 | 64 | 256 |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 19 | 181 | 1150 | 3620 |
| 4096 | 19 | 171 | 960 | 2161 |
| 32768 | 14 | 120 | 534 | 714 |

### openai/gpt-oss-20b

| prefix \ N | 1 | 8 | 64 | 256 |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 54 | 334 | 1615 | 4452 |
| 4096 | 47 | 282 | 1593 | 3167 |
| 32768 | 26 | 168 | 627 | 995 |

vs the 2026-04-25 run on 26.03 (below): single-stream 54 vs 48; N=256/prefix-1
4452 vs 2332 — vLLM 0.22 is a real speedup (different KV budgets, so not a
perfectly controlled comparison).

### Qwen/Qwen3.6-27B-FP8 (partial — slow dense model)

| prefix \ N | 1 | 8 | 64 | 256 |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 7.9 | 60 | 286 | 386 |
| 4096 | 7.6 | 46 | 98 | – |
| 32768 | – | – | – | – |

~8 tok/s single-stream is bandwidth math: ~29 GB of dense weights per token
on a ~273 GB/s box.

### nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16 (partial)

| prefix \ N | 1 | 8 | 64 | 256 |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 28 | 143 | 523 | – |
| 4096 | 27 | 122 | 188 | – |
| 32768 | 19 | 35 | 35 | – |

### Qwen/Qwen3.6-35B-A3B-FP8

| prefix \ N | 1 | 8 | 64 | 256 |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 53 | 271 | 913 | 794 |
| 4096 | 49 | 127 | 241 | 93 |
| 32768 | 29 | 45 | 30 | – |

Inversions at high N with long prefixes = KV-cache pressure → preemption;
for long-context work this model saturates around N=64 on this box.

### google/gemma-4-26B-A4B-it

| prefix \ N | 1 | 8 | 64 | 256 |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 24 | 178 | 1119 | 3320 |
| 4096 | 22 | 187 | 817 | 1411 |
| 32768 | 15 | 118 | 486 | 638 |

Best long-context scaling of the big models (sliding-window attention).

### Qwen/Qwen3.6-35B-A3B (BF16)

| prefix \ N | 1 | 8 | 64 | 256 |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 30 | 198 | 619 | – |
| 4096 | 29 | 84 | 172 | – |
| 32768 | 19 | 32 | 28 | – |

FP8 variant is ~1.8× faster single-stream (53 vs 30) — bandwidth-bound, so
prefer FP8 in practice.

### google/gemma-4-31B-it (resharded, partial)

| prefix \ N | 1 | 8 | 64 | 256 |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 4 | 28 | 152 | – |
| 4096 | 4 | 26 | 116 | – |
| 32768 | 3 | 19 | 68 | – |

Slowest of the fleet, as bandwidth math predicts: ~62 GB of dense BF16
weights per token. Usable interactively only at low concurrency; the
QAT w4a16 variant would be ~4× faster if 31B quality is ever needed at
speed.

### Not benchmarked

`Qwen/Qwen2.5-0.5B-Instruct` (first attempt used 36 000 ctx > its 32 768
native; requeue was cancelled when the machine had to shut down) and
`openai/gpt-oss-120b` (queue stopped at user request before its slot; runs
on 26.03.post1 only). `google/gemma-4-12B-it` cannot serve at all
([models.md](./models.md)).

## 2026-04-25 baseline — gpt-oss-20b on 26.03.post1

Service config: `--max-model-len 131072`, `--gpu-memory-utilization 0.75`,
full grid, `GEN_BUDGET_PER_CELL` = 131 072 tokens, output 64–1024/request.

| prefix tokens |   1 |   4 |  16 |  64 | 256 | 1024 | prefill (s) |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
|     1 |  48 | 137 | 318 | 734 | 2332 | 2807 |  0.03 |
|  4096 |  44 | 105 | 335 | 957 | 2215 | 2436 |  0.54 |
| 32768 |  31 |  96 | 223 | 459 |  964 | 1133 |  7.82 |
| 98304 |  12 |  27 |  87 | 222 |  539 |  428 | 49.16 |

Prefill column from [`bench_prefill.py`](./bench_prefill.py): one request per
prefix length with `max_tokens=1` and a fresh random prefix (cold prefix
cache). Note 96 k prefill is ~54 s, far above the naive
"length / peak-prompt-throughput" estimate — chunked-prefill peaks of
~10 k tok/s aren't sustained as context grows because attention cost is
super-linear.

To re-run the full grid against the production service:
`VLLM_API_KEY=$(sudo grep ^VLLM_API_KEY /etc/vllm/env | cut -d= -f2)
python3 spark/inference/bench_vllm.py`. The bench scripts read
`VLLM_API_KEY` from the environment; without it every request 401s. Tweak
`PREFIX_LENGTHS`, `CONCURRENCIES`, or `OUTPUT_TOKENS_MIN/MAX` at the top.
