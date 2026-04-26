#!/usr/bin/env bash
# Serve vLLM in the foreground, mirroring the /etc/systemd/system/vllm.service
# unit but runnable by hand. Useful for debugging startup failures without
# fighting journald. Auto-stops the systemd service if it's active so port
# 8000 is free.
#
#   ./serve-vllm.sh                       # uses /etc/vllm/env
#   VLLM_MODEL=openai/gpt-oss-20b ./serve-vllm.sh   # override

set -euo pipefail

if systemctl is-active --quiet vllm; then
  echo "[serve-vllm] stopping vllm.service (sudo)"
  sudo systemctl stop vllm
fi

ENV_FILE=${VLLM_ENV_FILE:-/etc/vllm/env}
if [[ -r "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
elif [[ -e "$ENV_FILE" ]]; then
  echo "[serve-vllm] $ENV_FILE not readable; re-reading via sudo"
  while IFS= read -r line; do
    [[ -z "$line" || "$line" == \#* ]] && continue
    export "$line"
  done < <(sudo cat "$ENV_FILE")
fi

: "${VLLM_MODEL:?set VLLM_MODEL or populate $ENV_FILE}"
: "${VLLM_EXTRA_ARGS:=--gpu-memory-utilization 0.75}"
: "${HF_TOKEN:=}"
: "${VLLM_API_KEY:=}"
: "${VLLM_IMAGE:=nvcr.io/nvidia/vllm:26.03.post1-py3}"
: "${VLLM_PORT:=8000}"
: "${VLLM_BIND:=127.0.0.1}"
: "${VLLM_HF_CACHE:=/srv/vllm/hf}"

docker rm -f vllm >/dev/null 2>&1 || true

exec docker run --rm --name vllm \
  --gpus all \
  --ipc=host \
  --shm-size=16g \
  -p "${VLLM_BIND}:${VLLM_PORT}:8000" \
  -v "${VLLM_HF_CACHE}:/root/.cache/huggingface" \
  -e HF_HOME=/root/.cache/huggingface \
  -e HF_TOKEN="$HF_TOKEN" \
  -e VLLM_API_KEY="$VLLM_API_KEY" \
  "$VLLM_IMAGE" \
  vllm serve "$VLLM_MODEL" \
  --host 0.0.0.0 --port 8000 \
  $VLLM_EXTRA_ARGS
