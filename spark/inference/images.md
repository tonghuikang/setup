# Container images

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
| `nvcr.io/nvidia/vllm:26.03.post1-py3` | 0.17.1 | previous production image; keep — `gpt-oss-120b` only serves on this one (26.06's MXFP4 MoE prep OOMs the host, see [failure-modes.md](./failure-modes.md)) |

When a newer NGC tag ships, re-test before switching: check the
instrumentator bug is fixed, and re-try `google/gemma-4-12B-it`
(`gemma4_unified` arch, unsupported by vLLM 0.22.1).

The `vllm-fixed` images were built with (from any directory):

```dockerfile
FROM nvcr.io/nvidia/vllm:26.06-py3
RUN pip install --no-cache-dir prometheus-fastapi-instrumentator==8.0.2
# 26.06-tf additionally:
RUN pip install --no-cache-dir -U transformers
```
