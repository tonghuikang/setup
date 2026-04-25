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
VLLM_MODEL=Qwen/Qwen2.5-0.5B-Instruct
VLLM_EXTRA_ARGS=--max-model-len 8192 --gpu-memory-utilization 0.85
VLLM_API_KEY=<64-hex-chars>
HF_TOKEN=
```

After editing: `sudo systemctl restart vllm`.

## Auth

vLLM enforces a Bearer token via its own `--api-key` flag. The key lives only
in `/etc/vllm/env` (root, 0600) — not in the repo. Read it with:

```sh
sudo grep ^VLLM_API_KEY /etc/vllm/env
```

There is **no Cloudflare Access policy** in front of `vllm.huikang.dev`; the
API key is the only gate. If multi-user / browser-flow auth becomes a thing,
add a Cloudflare Access self-hosted application on the hostname.

## Operations

```sh
# Status / logs
sudo systemctl status vllm
sudo journalctl -u vllm -f
sudo docker logs -f vllm

# Restart after env change
sudo systemctl restart vllm

# Stop
sudo systemctl stop vllm
```

First boot of a new model: the container downloads weights from HuggingFace
into `/srv/vllm/hf`, which can take many minutes for large models. Subsequent
restarts hit cache and start in seconds.

## Querying

From this box (and any client with the API key):

```sh
KEY=$(sudo grep ^VLLM_API_KEY /etc/vllm/env | cut -d= -f2)

curl -s https://vllm.huikang.dev/v1/chat/completions \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen2.5-0.5B-Instruct",
    "messages": [{"role":"user","content":"Say hello in one word."}]
  }'
```

OpenAI Python client:

```python
from openai import OpenAI
c = OpenAI(base_url="https://vllm.huikang.dev/v1", api_key="...")
c.chat.completions.create(
    model="Qwen/Qwen2.5-0.5B-Instruct",
    messages=[{"role": "user", "content": "hi"}],
)
```

## Switching models

Edit `/etc/vllm/env`:

```
VLLM_MODEL=openai/gpt-oss-120b
```

then `sudo systemctl restart vllm`. The first restart will pull ~60 GB of
MXFP4 weights into `/srv/vllm/hf`. Watch with `journalctl -u vllm -f`; once
the server logs `Application startup complete`, it's ready.

Tested models on this box:

- `Qwen/Qwen2.5-0.5B-Instruct` — smoke-test, ~1 GB, starts in ~30 s.
- `openai/gpt-oss-120b` — production target, MoE 117B / 5.1B active, MXFP4
  native, fits in the 128 GB unified memory.

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
