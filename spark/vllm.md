# Spark — vLLM inference server

OpenAI-compatible LLM serving on the GB10, exposed at `https://vllm.huikang.dev`
through the same Cloudflare Tunnel that fronts SSH. Setup performed 2026-04-25.

## Why this image

`vllm/vllm-openai` and the upstream PyPI wheels are **compiled for sm_120 max**.
The GB10 is **sm_121**, so the stock image starts but every CUDA kernel launch
fails with `CUDA error: no kernel image is available for execution`.

NVIDIA publishes an aarch64 + CUDA 13 + sm_121 build on NGC:

```
nvcr.io/nvidia/vllm:26.03.post1-py3
```

This is the only container that has worked end-to-end on Spark without source
patches. Newer monthly tags (`26.04-py3`, …) are published on the same
namespace; bump the tag in `/etc/vllm/env` when a newer one ships.

## Architecture

```
client → https://vllm.huikang.dev → Cloudflare edge → Cloudflare Tunnel
       → cloudflared.service on Spark → http://localhost:8000
       → docker container "vllm" (NGC image) → /v1/chat/completions
```

Same tunnel as SSH (`spark.huikang.dev`); just an additional ingress rule. SSH
and HTTP can't share one hostname (different protocols at the tunnel layer),
so vLLM lives at its own subdomain.

## Files on disk

| Path | Owner | Purpose |
| --- | --- | --- |
| `/etc/systemd/system/vllm.service` | root | systemd unit, runs the container |
| `/etc/vllm/env` | root, 0600 | model selection + API key + HF token |
| `/srv/vllm/hf` | htong | HuggingFace model cache (persistent across container restarts) |
| `/etc/cloudflared/config.yml` | root | adds `vllm.huikang.dev` ingress |

`/etc/vllm/env` is the only knob you need to touch in normal operation:

```
VLLM_MODEL=openai/gpt-oss-20b
VLLM_EXTRA_ARGS=--gpu-memory-utilization 0.85
HF_TOKEN=
```

After editing: `sudo systemctl restart vllm`.

For ad-hoc debugging, `spark/serve-vllm.sh` runs the same docker invocation
in the foreground. It auto-stops `vllm.service` (via `sudo`) so port 8000 is
free:

```sh
./spark/serve-vllm.sh                                  # reads /etc/vllm/env
VLLM_MODEL=openai/gpt-oss-20b ./spark/serve-vllm.sh    # override
```

## Auth

There is **no auth** on `vllm.huikang.dev`. The hostname is publicly
resolvable and any client can hit `/v1/*` directly. Acceptable here because
the box is a personal dev workstation and the hostname isn't advertised, but
if abuse shows up the two natural gates are:

- **vLLM `--api-key`** — re-add `--api-key "$VLLM_API_KEY"` to the
  `ExecStart` line and put a key in `/etc/vllm/env`. Bearer-token, OpenAI
  client-compatible.
- **Cloudflare Access** self-hosted application on `vllm.huikang.dev` with
  an email-domain policy. Browser-friendly; clients need a service token.

## Operations

```sh
# Status / logs (no sudo needed — htong is in adm + docker groups)
systemctl status vllm
journalctl -u vllm -f
docker logs -f vllm

# Restart after env change
sudo systemctl restart vllm

# Stop
sudo systemctl stop vllm
```

First boot of a new model: the container downloads weights from HuggingFace
into `/srv/vllm/hf`, which can take many minutes for large models. Subsequent
restarts hit cache and start in seconds.

## Querying

From any client, no auth:

```sh
curl -s https://vllm.huikang.dev/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "openai/gpt-oss-20b",
    "messages": [{"role":"user","content":"Say hello in one word."}]
  }'
```

OpenAI Python client (the SDK requires a key string but the server ignores
it):

```python
from openai import OpenAI
c = OpenAI(base_url="https://vllm.huikang.dev/v1", api_key="not-required")
c.chat.completions.create(
    model="openai/gpt-oss-20b",
    messages=[{"role": "user", "content": "hi"}],
)
```

## Throughput

Measured 2026-04-25 against `http://localhost:8000` with `openai/gpt-oss-20b`
on the GB10, `max_model_len=131072`, `--gpu-memory-utilization 0.85`, no
other vLLM flags (so `max_num_seqs` is the engine default). Harness is
`spark/bench_vllm.py`:

- `/v1/completions` with `prompt` as raw token-ID arrays (no tokenizer in
  the loop, prompts/completions are gibberish — that's intentional).
- Each request: random-token prefix of length L, output length sampled
  uniformly from `[128, 1024]`, pinned via `min_tokens=max_tokens` and
  `ignore_eos=True` so every request emits exactly the requested length.
- Distinct per-request seed for the prefix tokens, so prefix caching is
  defeated (real engine work, not cache hits).
- Per-cell budget: ~131 072 (= 2¹⁷) generation tokens, with at least N
  requests so the engine sees a full first batch even at long prefixes.
- One warmup pass per prefix length before timing.
- Bypasses the Cloudflare tunnel because long-prefix prefills (~96 k
  tokens) easily blow Cloudflare's 100 s edge timeout.

Cell value is **total generation throughput (output tokens per second)** =
`sum(completion_tokens) / wall_time` across all requests in the cell, so
queued completions count.

| prefix tokens \ concurrency |   1 |   4 |  16 |  64 | 256 |
| ---: | ---: | ---: | ---: | ---: | ---: |
|     1 |  48 | 124 | 277 |  874 | 2666 |
|  1024 |  47 | 122 | 295 |  746 | 1438 |
| 16384 |  35 |  64 | 107 |  118 |    — |
| 98304 |   — |   — |   — |    — |    — |

> Numbers are from the previous 1 M-budget run. The 1 M cells finished but
> took too long; the current 128 k-generation-budget run is in flight and
> these will be replaced once it completes. Empty cells are pending. Engine
> logs during the run show running batch peaking at 69–97 reqs (KV cache /
> chunked-prefill bound), so concurrencies past that mostly extend the
> queue rather than raising throughput.

To re-run: `python3 spark/bench_vllm.py`. Tweak `PREFIX_LENGTHS`,
`CONCURRENCIES`, `OUTPUT_TOKENS_MIN/MAX`, or `GEN_TOKENS_BUDGET` at the top.

## Switching models

Edit `/etc/vllm/env`:

```
VLLM_MODEL=openai/gpt-oss-20b
```

then `sudo systemctl restart vllm`. The first restart will pull ~13 GB of
MXFP4 weights into `/srv/vllm/hf`. Watch with `journalctl -u vllm -f`; once
the server logs `Application startup complete`, it's ready.

Tested models on this box:

- `Qwen/Qwen2.5-0.5B-Instruct` — smoke-test, ~1 GB, starts in ~30 s.
- `openai/gpt-oss-20b` — production target, MoE 21B / 3.6B active, MXFP4
  native, ~13 GB, comfortably fits in the 128 GB unified memory.
- `openai/gpt-oss-120b` — larger sibling, MoE 117B / 5.1B active, MXFP4
  native, ~60 GB; still fits but leaves less headroom for the desktop.

For larger non-MoE models, check `nvidia-smi`'s memory column — the GB10's
unified memory is shared with the desktop session, so leave headroom for X
and any apps you're running.

## Failure modes

- Container crashes immediately with `CUDA error: no kernel image …` →
  the image tag isn't sm_121-aware. Verify `/etc/vllm/env` has the
  NGC tag, not `vllm/vllm-openai`.
- Container OOMs on startup → lower `--gpu-memory-utilization` in
  `VLLM_EXTRA_ARGS`, or pick a smaller / quantized model.
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

## Tear down

```sh
sudo systemctl disable --now vllm
sudo rm /etc/systemd/system/vllm.service
sudo rm -rf /etc/vllm
sudo systemctl daemon-reload
sudo docker rmi nvcr.io/nvidia/vllm:26.03.post1-py3
sudo rm -rf /srv/vllm
```

Then remove the `vllm.huikang.dev` ingress block from
`/etc/cloudflared/config.yml`, restart `cloudflared`, and:

```sh
cloudflared tunnel route dns --overwrite-dns spark <other-host>  # or delete via dashboard
```
