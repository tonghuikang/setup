# Spark — LLM inference

OpenAI-compatible LLM serving on the GB10, exposed at `https://vllm.huikang.dev`
through the same Cloudflare Tunnel that fronts SSH. Setup performed 2026-04-25;
last major refresh 2026-07-03 (vLLM 26.06, 13-model test sweep, benchmarks).

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

## Docs

| File | Contents |
| --- | --- |
| [images.md](./images.md) | which container images work on sm_121 and why |
| [service.md](./service.md) | operating the systemd service: start/stop, auth, querying, switching models, teardown |
| [models.md](./models.md) | models on disk + serve-test results |
| [benchmarks.md](./benchmarks.md) | throughput methodology + results |
| [failure-modes.md](./failure-modes.md) | crashes and their fixes — read before loading a big model |

## Scripts

| File | Purpose |
| --- | --- |
| [serve-vllm.sh](./serve-vllm.sh) | run the service's docker invocation in the foreground (debugging) |
| [bench_vllm.py](./bench_vllm.py) | decode-throughput sweep: concurrency × shared-prefix length |
| [bench_prefill.py](./bench_prefill.py) | prefill latency vs context length (`max_tokens=1`) |
| [bench-results/](./bench-results/) | raw benchmark outputs, 2026-07-03 |
