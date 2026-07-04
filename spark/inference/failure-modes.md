# Failure modes

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
- Container crashes immediately with `CUDA error: no kernel image …` →
  the image tag isn't sm_121-aware. Verify the unit runs an NGC/sm_121
  image, not `vllm/vllm-openai`. See [images.md](./images.md).
- Container OOMs on startup → lower `--gpu-memory-utilization` in
  `VLLM_EXTRA_ARGS`, or pick a smaller / quantized model.
- Every request 500s with `'_IncludedRouter' object has no attribute
  'path'`, engine logs look healthy → raw NGC 26.06 middleware bug; use
  `vllm-fixed:26.06` ([images.md](./images.md)).
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
