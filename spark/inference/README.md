# Spark — LLM inference

OpenAI-compatible LLM serving on the GB10, exposed at `https://vllm.huikang.dev`
through the same Cloudflare Tunnel that fronts SSH. Setup performed 2026-04-25;
last major refresh 2026-07-03 (vLLM 26.06, 13-model test sweep, benchmarks).

Companion docs: [service.md](./service.md) (operating the systemd service:
start/stop, auth, querying, switching models, teardown) and
[benchmarks.md](./benchmarks.md) (throughput + prefill results).
Scripts: [serve-vllm.sh](./serve-vllm.sh) (run the service's docker
invocation in the foreground), [bench_vllm.py](./bench_vllm.py) (benchmark
harness), [bench-results/](./bench-results/) (raw outputs).

## Architecture

```
client → https://vllm.huikang.dev → Cloudflare edge → Cloudflare Tunnel
       → cloudflared.service on Spark → http://localhost:8000
       → docker container "vllm" (NGC image) → /v1/chat/completions
```

Same tunnel as SSH (`spark.huikang.dev`); just an additional ingress rule. SSH
and HTTP can't share one hostname (different protocols at the tunnel layer),
so vLLM lives at its own subdomain.

## Files on disk (host)

| Path | Owner | Purpose |
| --- | --- | --- |
| `/etc/systemd/system/vllm.service` | root | systemd unit, runs the container |
| `/etc/vllm/env` | root, 0600 | model selection + API key + HF token |
| `/srv/vllm/hf` | htong | HF model cache for the service |
| `~/.cache/huggingface` | htong | HF model cache for htong's downloads |
| `/etc/cloudflared/config.yml` | root | adds `vllm.huikang.dev` ingress |

## Container images

`vllm/vllm-openai` and the upstream PyPI wheels are **compiled for sm_120 max**.
The GB10 is **sm_121**, so the stock image starts but every CUDA kernel launch
fails with `CUDA error: no kernel image is available for execution`. Only
NVIDIA's aarch64 + CUDA 13 + sm_121 builds on NGC (`nvcr.io/nvidia/vllm`)
work on Spark.

Images on disk (as of 2026-07-03):

| Tag | vLLM | Status |
| --- | --- | --- |
| `vllm-fixed:26.06` (local) | 0.22.1 | **preferred** — NGC `26.06-py3` + `prometheus-fastapi-instrumentator` 8.0.2 |
| `vllm-fixed:26.06-tf` (local) | 0.22.1 | above + `transformers` 5.13, for newer HF architectures |
| `nvcr.io/nvidia/vllm:26.06-py3` | 0.22.1 | **broken as shipped**: pins instrumentator 8.0.0, which 500s every HTTP request under its FastAPI (`'_IncludedRouter' object has no attribute 'path'`). Engine loads fine, so logs look healthy while serving nothing |
| `nvcr.io/nvidia/vllm:26.03.post1-py3` | 0.17.1 | previous production image; keep — `gpt-oss-120b` only serves on this one (26.06's MXFP4 MoE prep OOMs the host, see Failure modes) |

When a newer NGC tag ships (checked 2026-07-12: 26.06 still newest), re-test
before switching: check the instrumentator bug is fixed, and if it carries
vLLM ≥ 0.23.0, serve `google/gemma-4-12B-it` (its `gemma4_unified` arch is
supported upstream since vLLM v0.23.0, 2026-06-15 — NVIDIA just hasn't
shipped a container with it yet).

The `vllm-fixed` images were built with:

```dockerfile
FROM nvcr.io/nvidia/vllm:26.06-py3
RUN pip install --no-cache-dir prometheus-fastapi-instrumentator==8.0.2
# 26.06-tf additionally:
RUN pip install --no-cache-dir -U transformers
```

## Models on this box

Two HF caches: `/srv/vllm/hf` (the service's store) and
`~/.cache/huggingface` (htong's downloads, incl. the gemma-4 family and
Qwen3.6-27B-FP8, added 2026-07-03).

Serve-tested 2026-07-03, one at a time, `vllm-fixed:26.06` unless noted
(smoke test = live chat completion through the OpenAI API):

| Model | Result | Notes |
| --- | --- | --- |
| `google/gemma-4-E2B-it` | ✅ | `~/.cache/huggingface` store |
| `google/gemma-4-E4B-it` | ✅ | |
| `google/gemma-4-12B-it` | ⏳ | arch `gemma4_unified` needs vLLM ≥ 0.23.0; no NGC container ships that yet (checked 2026-07-12). Verified working 2026-07-12 via a temporary backport of the v0.23.0 model file onto `26.06-tf` (required `--attention-backend TRITON_ATTN`; benchmarked, see [benchmarks.md](./benchmarks.md)), since removed — wait for the next NGC tag |
| `google/gemma-4-26B-A4B-it` | ✅ | MoE |
| `google/gemma-4-31B-it` | ✅* | only via resharded copy `~/.cache/huggingface/gemma-4-31B-it-resharded` (31×2 GB shards), `--gpu-memory-utilization ≥0.60`. Original 47 GB shard file hard-crashes the box (see Failure modes) |
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
and any apps you're running. Throughput per model:
[benchmarks.md](./benchmarks.md).

## Failure modes

- **Whole machine hard-reboots during model load** — unified memory
  exhaustion does not degrade gracefully (no OOM-kill; the box dies).
  Root causes seen 2026-07-03: (a) two vLLM instances at once (the old
  `Restart=always` service resurrecting itself under a test instance —
  autostart is disabled now for this reason); (b) a checkpoint with a
  huge single safetensors file — the load transient scales with the
  *largest file*, because file pages race the GPU pool for the same RAM.
  `gemma-4-31B-it` ships a 47 GB shard and killed the box twice; fix was
  resharding it to 2 GB pieces (`~/.cache/huggingface/gemma-4-31B-it-resharded`).
  Rules: one vLLM at a time, `--gpu-memory-utilization ≤ 0.70`, reshard
  any checkpoint whose largest file exceeds ~10 GB, and for a first-time
  load of a big model run a watchdog that kills the container if host
  MemAvailable drops below ~4 GB.
- EngineCore dies during startup KV-cache profiling with
  `RuntimeError: … 'BatchPrefillWithPagedKVCacheDispatched' … Unsupported
  max_mma_kv: 0` → FlashInfer (the default attention backend) can't handle
  the model; add `--attention-backend TRITON_ATTN`. Seen 2026-07-12 running
  gemma-4-12B-it via a v0.23.0 model-file backport on 26.06. Note
  `VLLM_ATTENTION_BACKEND` is ignored by this build — only the CLI flag
  works.
- Container crashes immediately with `CUDA error: no kernel image …` →
  the image tag isn't sm_121-aware. Verify the unit runs an NGC/sm_121
  image (see Container images above), not `vllm/vllm-openai`.
- Container OOMs on startup → lower `--gpu-memory-utilization` in
  `VLLM_EXTRA_ARGS`, or pick a smaller / quantized model.
- Every request 500s with `'_IncludedRouter' object has no attribute
  'path'`, engine logs look healthy → raw NGC 26.06 middleware bug; use
  `vllm-fixed:26.06` (see Container images above).
- `curl https://vllm.huikang.dev/v1/models` returns 502 → the container
  hasn't finished startup. Tail the logs.
- `Permission denied` on `/srv/vllm/hf` from inside the container →
  the bind-mount target perms drifted; `sudo chown -R htong:htong /srv/vllm`.
- `Starting to load model …` then silence; container alive, no further log
  lines for many minutes → HuggingFace's Xet/CDN backend
  (`cas-bridge.xethub.hf.co`) hung mid-stream and `huggingface_hub` left the
  socket in `CLOSE_WAIT` instead of retrying. Workaround used here:
  pre-download the safetensors blob directly with `curl -L --fail -C -` from
  `https://huggingface.co/<repo>/resolve/main/model.safetensors` into
  `/srv/vllm/hf/hub/models--<org>--<name>/blobs/<sha256>`, then
  `ln -s ../../blobs/<sha256> snapshots/<commit>/model.safetensors`, then
  restart vllm so it loads from cache. `curl -C -` is resumable; the chunky
  HF Python client is not.
