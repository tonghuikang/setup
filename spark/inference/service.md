# Operating the vLLM service

## Config

`/etc/vllm/env` is the only knob you need to touch in normal operation:

```
VLLM_MODEL=openai/gpt-oss-20b
VLLM_EXTRA_ARGS=--gpu-memory-utilization 0.75
HF_TOKEN=
VLLM_API_KEY=<bearer token clients must send>
```

After editing: `sudo systemctl restart vllm`. The container image tag is
hardcoded in `/etc/systemd/system/vllm.service` (edit + `sudo systemctl
daemon-reload` to change it).

For ad-hoc debugging, [`serve-vllm.sh`](./serve-vllm.sh) runs the same docker
invocation in the foreground. It auto-stops `vllm.service` (via `sudo`) so
port 8000 is free:

```sh
./spark/inference/serve-vllm.sh                                  # reads /etc/vllm/env
VLLM_MODEL=openai/gpt-oss-20b ./spark/inference/serve-vllm.sh    # override
```

## Start / stop

**Autostart is disabled** (2026-07-03): the box no longer serves on boot,
and stopping the service no longer triggers an auto-restart fight over
memory. Start it when you want it:

```sh
sudo systemctl start vllm     # serve gpt-oss-20b (per /etc/vllm/env)
sudo systemctl enable vllm    # re-enable start-on-boot, if ever wanted

# Status / logs (no sudo needed — htong is in adm + docker groups)
systemctl status vllm
journalctl -u vllm -f
docker logs -f vllm

# Restart after env change
sudo systemctl restart vllm

# Stop
sudo systemctl stop vllm
```

## Switching models

Edit `VLLM_MODEL` in `/etc/vllm/env`, then `sudo systemctl restart vllm`.
First boot of a new model downloads weights into `/srv/vllm/hf`, which can
take many minutes; subsequent restarts hit cache and start in seconds. Watch
with `journalctl -u vllm -f`; once the server logs `Application startup
complete`, it's ready. See the models table in [README.md](./README.md#models-on-this-box) for what runs on this
box and [failure modes](./README.md#failure-modes) **before loading anything
with big safetensors files**.

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

## Tear down

```sh
sudo systemctl disable --now vllm
sudo rm /etc/systemd/system/vllm.service
sudo rm -rf /etc/vllm
sudo systemctl daemon-reload
sudo docker rmi vllm-fixed:26.06 vllm-fixed:26.06-tf \
  nvcr.io/nvidia/vllm:26.06-py3 nvcr.io/nvidia/vllm:26.03.post1-py3
sudo rm -rf /srv/vllm
```

Then remove the `vllm.huikang.dev` ingress block from
`/etc/cloudflared/config.yml`, restart `cloudflared`, and:

```sh
cloudflared tunnel route dns --overwrite-dns spark <other-host>  # or delete via dashboard
```
