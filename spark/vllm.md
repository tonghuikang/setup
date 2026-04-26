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
VLLM_EXTRA_ARGS=--gpu-memory-utilization 0.75
HF_TOKEN=
VLLM_API_KEY=<bearer token clients must send>
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

Bearer-token auth is enabled. The key lives in `/etc/vllm/env` as
`VLLM_API_KEY` and the systemd unit forwards it into the container via
`-e VLLM_API_KEY`; vLLM's middleware picks it up automatically (no
`--api-key` flag needed) and gates **every path under `/v1/*`**. Requests
without a matching `Authorization: Bearer <key>` header get `401
Unauthorized`.

What stays open without a token (per vLLM's `AuthenticationMiddleware`):

- `OPTIONS` preflight on any path
- Anything not under `/v1` — `/health`, `/version`, `/ping`, `/metrics`,
  `/docs`, `/openapi.json`

So `/v1/models` is **not** publicly enumerable; clients must already know
the model name (or have the key).

To rotate the key: edit `VLLM_API_KEY` in `/etc/vllm/env` and
`sudo systemctl restart vllm`. To disable auth, blank the value or remove
the line entirely.

If browser-based access matters more than CLI ergonomics, **Cloudflare
Access** in front of `vllm.huikang.dev` (email-domain policy + service
tokens for non-browser clients) is a drop-in replacement for the bearer
token at the edge.

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

Set `VLLM_API_KEY` in your shell to the value from `/etc/vllm/env`, then:

```sh
curl -s https://vllm.huikang.dev/v1/chat/completions \
  -H "Authorization: Bearer $VLLM_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "openai/gpt-oss-20b",
    "messages": [{"role":"user","content":"Say hello in one word."}]
  }'
```

OpenAI Python client:

```python
import os
from openai import OpenAI
c = OpenAI(base_url="https://vllm.huikang.dev/v1",
           api_key=os.environ["VLLM_API_KEY"])
c.chat.completions.create(
    model="openai/gpt-oss-20b",
    messages=[{"role": "user", "content": "hi"}],
)
```

## Throughput

**Setup.** Measured 2026-04-25 on **Spark** (NVIDIA GB10, sm_121, 128 GB
unified memory, aarch64) running the NGC container
`nvcr.io/nvidia/vllm:26.03.post1-py3` (vLLM 0.17.1+bd67d66a, the only image
that has working sm_121 kernels). Model `openai/gpt-oss-20b`
(MoE 21B / 3.6B active, MXFP4 native, ~13 GB on disk) loaded from the local
HF cache at `/srv/vllm/hf`. vLLM args: `--max-model-len 131072` (the
model's native context — no truncation), `--gpu-memory-utilization 0.75`
(was 0.85 — leaving more headroom outside vLLM's reservation, since on a
unified-memory box like Spark the reservation comes out of system RAM and
0.85 left the host with only ~10 GB free, enough to OOM under a 1024-way
burst),
no other flags, so `max_num_seqs` etc. fall back to engine defaults.
Service runs as the `vllm.service` systemd unit; the benchmark hits
`http://localhost:8000/v1/completions` directly to avoid the Cloudflare
Tunnel's 100 s edge timeout that otherwise kills long-prefix prefills.

Harness is `spark/bench_vllm.py`:

- `/v1/completions` with `prompt` as a raw token-ID array (no tokenizer in
  the loop; prompts/completions are gibberish — that's intentional).
- Each cell of `(N, prefix_tokens)` sends N concurrent requests that **share
  one random prefix** of length `prefix_tokens`. vLLM's prefix cache absorbs
  the prefill cost after the first request, so each cell measures decode
  throughput at concurrency N once the shared prefill is amortized
  (representative of shared-context workloads — long system prompt or
  shared document).
- Per-request output length is deterministic and identical for all N
  requests in a cell: `output_tokens = clamp(131 072 / N, 64, 1024)`.
  Pinned via `min_tokens=max_tokens` and `ignore_eos=True`, so the engine
  emits exactly that many tokens regardless of model behavior. Cells where
  N ≤ 128 hit the 1024 ceiling; cells with N ≥ 2048 would hit the 64
  floor; in between the budget splits evenly. Total generation per cell is
  131 072 tokens (= `GEN_BUDGET_PER_CELL`).
- One warmup pass at the start of the run (8 concurrent, 64-token shared
  prefix, 16-token output) — settles engine state, not a per-cell warmup.

Cell value is **total generation throughput (output tokens per second)** =
`sum(completion_tokens) / wall_time` across all N requests in the cell.

| prefix tokens |   1 |   4 |  16 |  64 | 256 | 1024 | prefill (s) |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
|     1 |  48 | 137 | 318 | 734 | 2332 | 2807 |  0.03 |
|  4096 |  44 | 105 | 335 | 957 | 2215 | 2436 |  0.54 |
| 32768 |  31 |  96 | 223 | 459 |  964 | 1133 |  7.82 |
| 98304 |  12 |  27 |  87 | 222 |  539 |  428 | 49.16 |

Prefill column comes from `spark/bench_prefill.py`: one request per prefix
length with `max_tokens=1` and a fresh random prefix (cold prefix cache).
Wall time is dominated by prefill (one decode step is tens of ms,
negligible). Note 96 k prefill is ~54 s, far above the naive
"length / peak-prompt-throughput" estimate — chunked-prefill peaks of
~10 k tok/s aren't sustained as context grows because attention cost is
super-linear.

> Run in flight; cells fill in as they complete.

To re-run: `VLLM_API_KEY=$(sudo grep ^VLLM_API_KEY /etc/vllm/env | cut -d= -f2)
python3 spark/bench_vllm.py`. The bench scripts read `VLLM_API_KEY` from
the environment and add the bearer header on every request; without it
they'll all 401. Tweak `PREFIX_LENGTHS`, `CONCURRENCIES`, or
`OUTPUT_TOKENS_MIN/MAX` at the top.

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
