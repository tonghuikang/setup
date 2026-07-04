# Models on this box

Two HF caches: `/srv/vllm/hf` (the service's store) and
`~/.cache/huggingface` (htong's downloads, incl. the gemma-4 family and
Qwen3.6-27B-FP8, added 2026-07-03).

Serve-tested 2026-07-03, one at a time, `vllm-fixed:26.06` unless noted
(smoke test = live chat completion through the OpenAI API):

| Model | Result | Notes |
| --- | --- | --- |
| `google/gemma-4-E2B-it` | ✅ | `~/.cache/huggingface` store |
| `google/gemma-4-E4B-it` | ✅ | |
| `google/gemma-4-12B-it` | ❌ | arch `gemma4_unified` unknown to vLLM 0.22.1; transformers-fallback also fails (shape mismatch). Re-check next NGC tag |
| `google/gemma-4-26B-A4B-it` | ✅ | MoE |
| `google/gemma-4-31B-it` | ✅* | only via resharded copy `~/.cache/huggingface/gemma-4-31B-it-resharded` (31×2 GB shards), `--gpu-memory-utilization ≥0.60`. Original 47 GB shard file hard-crashes the box (see [failure-modes.md](./failure-modes.md)) |
| `Qwen/Qwen3.6-27B-FP8` | ✅ | thinking model |
| `Qwen/Qwen2.5-0.5B-Instruct` | ✅ | smoke-test, ~1 GB, starts in ~30 s; native ctx only 32 768 |
| `Qwen/Qwen3-0.6B` | ✅ | |
| `Qwen/Qwen3.6-35B-A3B` | ✅ | MoE, ~70 GB BF16 |
| `Qwen/Qwen3.6-35B-A3B-FP8` | ✅ | |
| `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16` | ✅ | MoE |
| `openai/gpt-oss-20b` | ✅ | production target, MXFP4 ~13 GB; works on 26.03 and 26.06 |
| `openai/gpt-oss-120b` | ✅ | **26.03.post1 only** — 26.06 MXFP4 prep OOMs the host |

(`hexgrad/Kokoro-82M` is TTS — not a vLLM model.)

For larger non-MoE models, check `nvidia-smi`'s memory column — the GB10's
unified memory is shared with the desktop session, so leave headroom for X
and any apps you're running. Throughput numbers per model:
[benchmarks.md](./benchmarks.md).
