#!/usr/bin/env python3
"""vLLM throughput + prefill benchmark (single consolidated harness).

Measures, against an already-running vLLM server:
  1. Prefill latency per prefix length — fresh (cold) prefix, max_tokens=1,
     best of 3. Wall time is prefill-dominated (one decode step is ~tens of
     ms). Runs first so it's always present even if the deadline cuts the
     sweep short.
  2. Decode throughput over a (shared-prefix length × concurrency) grid.
     Each cell sends N concurrent requests sharing ONE random prefix; vLLM's
     prefix cache absorbs the prefill after the first request, so the cell
     measures decode throughput at concurrency N (shared-context workloads:
     long system prompt / shared document). The timed window still includes
     that one prefill, so low-N long-prefix cells are partly prefill-bound.

Prompts are raw token-ID arrays (no tokenizer in the loop; text is
gibberish — intentional, and model-agnostic). Output length is pinned via
min_tokens=max_tokens + ignore_eos, so the engine emits exactly the asked
tokens. Cell value = sum(completion_tokens) / wall = output tok/s.

Cells run low-concurrency-first (all prefixes at N=1, then N=8, …), so a
deadline cut still leaves complete low-N data. Cells that can't fit in the
context window are skipped; cells whose requests fail are marked ERR and the
sweep continues.

Config via env:
  BENCH_MODEL          model name (required; must match the served model)
  BENCH_URL            default http://localhost:8000/v1/completions
  VLLM_API_KEY         bearer token, if the server requires one
  BENCH_MAX_CTX        context budget; cells with prefix+output beyond it
                       are skipped (default 36000)
  BENCH_DEADLINE_S     stop starting new cells after this (0 = no deadline;
                       default 1620 = 27 min)
  BENCH_PREFIXES       comma-separated (default 1,4096,32768)
  BENCH_CONCURRENCIES  comma-separated (default 1,8,64,256)
  BENCH_CELL_BUDGET    output tokens per cell (default 32768)
  BENCH_OUT_MIN/MAX    per-request output clamp (default 64/512)

Examples:
  # reduced grid against a test container on 8001
  BENCH_MODEL=google/gemma-4-E2B-it \
  BENCH_URL=http://localhost:8001/v1/completions python3 bench_vllm.py

  # full grid against the production service (2026-04-25 style)
  VLLM_API_KEY=$(sudo grep ^VLLM_API_KEY /etc/vllm/env | cut -d= -f2) \
  BENCH_MODEL=openai/gpt-oss-20b BENCH_MAX_CTX=131072 BENCH_DEADLINE_S=0 \
  BENCH_PREFIXES=1,4096,32768,98304 BENCH_CONCURRENCIES=1,4,16,64,256,1024 \
  BENCH_CELL_BUDGET=131072 BENCH_OUT_MAX=1024 python3 bench_vllm.py
"""
import json, time, urllib.request, concurrent.futures as cf, random, sys, threading, os

# Default thread stack is 8 MB; with 1024 threads that's 8 GB of virtual
# memory, enough to draw OOM-killer attention on a box where vLLM owns most
# of the unified memory. 512 KB is plenty for a urllib thread.
threading.stack_size(512 * 1024)

URL = os.environ.get("BENCH_URL", "http://localhost:8000/v1/completions")
MODEL = os.environ["BENCH_MODEL"]
API_KEY = os.environ.get("VLLM_API_KEY", "")
MAX_CTX = int(os.environ.get("BENCH_MAX_CTX", "36000"))
DEADLINE_S = float(os.environ.get("BENCH_DEADLINE_S", "1620")) or float("inf")
PREFIX_LENGTHS = [int(x) for x in os.environ.get("BENCH_PREFIXES", "1,4096,32768").split(",")]
CONCURRENCIES = [int(x) for x in os.environ.get("BENCH_CONCURRENCIES", "1,8,64,256").split(",")]
GEN_BUDGET_PER_CELL = int(os.environ.get("BENCH_CELL_BUDGET", str(32 * 1024)))
OUTPUT_TOKENS_MIN = int(os.environ.get("BENCH_OUT_MIN", "64"))
OUTPUT_TOKENS_MAX = int(os.environ.get("BENCH_OUT_MAX", "512"))

# Middle of every relevant vocab (Qwen ~151k, gemma 262k, o200k ~201k),
# dodging specials/reserved IDs. A small range is fine — vLLM still attends
# over the whole prefix.
TOK_LO, TOK_HI = 1000, 100_000
T_START = time.perf_counter()


def random_token_ids(n_tokens, seed):
    rng = random.Random(seed)
    return [rng.randint(TOK_LO, TOK_HI) for _ in range(n_tokens)]


def one(prompt_ids, output_tokens):
    body = json.dumps({
        "model": MODEL,
        "prompt": prompt_ids,
        "max_tokens": output_tokens,
        "min_tokens": output_tokens,   # vLLM extension
        "ignore_eos": True,            # vLLM extension
        "temperature": 0.0,
        "stop": [],
    }).encode()
    headers = {"Content-Type": "application/json", "User-Agent": "curl/8.5.0"}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
    req = urllib.request.Request(URL, data=body, headers=headers)
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=1200) as r:
        data = json.loads(r.read())
    dt = time.perf_counter() - t0
    u = data["usage"]
    return dt, u["prompt_tokens"], u["completion_tokens"]


def sweep_cell(N, prefix_tokens, seed_base):
    shared_prefix = random_token_ids(prefix_tokens, seed=seed_base)
    out_tok = max(OUTPUT_TOKENS_MIN, min(OUTPUT_TOKENS_MAX, GEN_BUDGET_PER_CELL // N))
    plan = [(shared_prefix, out_tok) for _ in range(N)]
    t0 = time.perf_counter()
    with cf.ThreadPoolExecutor(max_workers=N) as ex:
        futs = [ex.submit(one, p, k) for (p, k) in plan]
        results = [f.result() for f in cf.as_completed(futs)]
    wall = time.perf_counter() - t0
    c_tok = sum(r[2] for r in results)
    p_tok = sum(r[1] for r in results)
    return c_tok / wall, len(plan), p_tok, c_tok, wall


def warmup():
    shared_prefix = random_token_ids(64, seed=99_000)
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(lambda pk: one(pk[0], pk[1]), [(shared_prefix, 16)] * 8))
    print("#   warmup done", file=sys.stderr, flush=True)


def measure_prefill():
    prefill = {}
    for L in PREFIX_LENGTHS:
        if L + 64 > MAX_CTX:
            continue
        walls = []
        for t in range(3):
            ids = random_token_ids(L, seed=77_000 + L * 10 + t)
            t0 = time.perf_counter()
            one(ids, 1)
            walls.append(time.perf_counter() - t0)
        prefill[L] = min(walls)
        print(f"PREFILL {json.dumps({'model': MODEL, 'prefix': L, 'best_s': round(prefill[L], 2), 'walls': [round(w, 2) for w in walls]})}", flush=True)
    return prefill


if __name__ == "__main__":
    print(f"# model={MODEL} max_ctx={MAX_CTX} deadline={DEADLINE_S}s "
          f"prefixes={PREFIX_LENGTHS} concurrencies={CONCURRENCIES} "
          f"cell_budget={GEN_BUDGET_PER_CELL}", flush=True)
    warmup()
    prefill = measure_prefill()

    results = {}
    seed_base = 1
    stopped = None
    # low concurrency first (across all prefixes), so a deadline cut still
    # leaves complete low-N data
    for N in CONCURRENCIES:
        for L in PREFIX_LENGTHS:
            if L + OUTPUT_TOKENS_MAX + 64 > MAX_CTX:
                results[(L, N)] = None
                continue
            elapsed = time.perf_counter() - T_START
            if elapsed > DEADLINE_S:
                stopped = f"deadline hit at {elapsed:.0f}s before L={L} N={N}"
                break
            try:
                tps, n_req, p_tok, c_tok, wall = sweep_cell(N, L, seed_base)
            except Exception as e:
                print(f"CELL-ERR L={L} N={N}: {type(e).__name__}: {e}", flush=True)
                seed_base += N + 7
                results[(L, N)] = None
                continue
            seed_base += n_req + 7
            results[(L, N)] = tps
            print(f"CELL {json.dumps({'model': MODEL, 'prefix': L, 'concurrency': N, 'out_tps': round(tps,1), 'wall_s': round(wall,1), 'prompt_tok': p_tok, 'gen_tok': c_tok})}", flush=True)
        if stopped:
            break

    header = "prefix \\ concurrency | " + " | ".join(f"{N:>6d}" for N in CONCURRENCIES) + " | prefill(s)"
    print(header, flush=True)
    print("-" * len(header), flush=True)
    for L in PREFIX_LENGTHS:
        cells = []
        for N in CONCURRENCIES:
            v = results.get((L, N))
            cells.append(f"{v:>6.0f}" if v else ("  skip" if (L, N) in results else "     -"))
        pf = f"{prefill[L]:>10.2f}" if L in prefill else "         -"
        print(f"{L:>20d} | " + " | ".join(cells) + f" | {pf}", flush=True)
    if stopped:
        print(f"# NOTE: {stopped}", flush=True)
    print(f"# total bench wall: {time.perf_counter()-T_START:.0f}s", flush=True)
