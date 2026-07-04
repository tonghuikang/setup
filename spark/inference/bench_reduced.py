#!/usr/bin/env python3
"""Reduced-grid throughput sweep for one model, adapted from spark/bench_vllm.py.

Env: BENCH_URL, BENCH_MODEL, BENCH_MAX_CTX, BENCH_DEADLINE_S, VLLM_API_KEY.
Grid: PREFIX x CONCURRENCY, 32k output tokens per cell, deadline-aware.
Emits one JSON line per cell (prefix "CELL ") plus the final table.
"""
import json, time, urllib.request, concurrent.futures as cf, random, sys, threading, os

threading.stack_size(512 * 1024)

URL = os.environ.get("BENCH_URL", "http://localhost:8001/v1/completions")
MODEL = os.environ["BENCH_MODEL"]
API_KEY = os.environ.get("VLLM_API_KEY", "")
MAX_CTX = int(os.environ.get("BENCH_MAX_CTX", "36000"))
DEADLINE_S = float(os.environ.get("BENCH_DEADLINE_S", "1620"))  # 27 min

OUTPUT_TOKENS_MIN = 64
OUTPUT_TOKENS_MAX = 512
GEN_BUDGET_PER_CELL = 32 * 1024

PREFIX_LENGTHS = [1, 4096, 32768]
CONCURRENCIES = [1, 8, 64, 256]

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
        "min_tokens": output_tokens,
        "ignore_eos": True,
        "temperature": 0.0,
        "stop": [],
    }).encode()
    t0 = time.perf_counter()
    headers = {"Content-Type": "application/json", "User-Agent": "curl/8.5.0"}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
    req = urllib.request.Request(URL, data=body, headers=headers)
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


if __name__ == "__main__":
    print(f"# model={MODEL} max_ctx={MAX_CTX} deadline={DEADLINE_S}s", flush=True)
    warmup()

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


    header = "prefix \\ concurrency | " + " | ".join(f"{N:>6d}" for N in CONCURRENCIES)
    print(header, flush=True)
    print("-" * len(header), flush=True)
    for L in PREFIX_LENGTHS:
        cells = []
        for N in CONCURRENCIES:
            v = results.get((L, N))
            cells.append(f"{v:>6.0f}" if v else ("  skip" if (L, N) in results else "     -"))
        print(f"{L:>20d} | " + " | ".join(cells), flush=True)
    if stopped:
        print(f"# NOTE: {stopped}", flush=True)
    print(f"# total bench wall: {time.perf_counter()-T_START:.0f}s", flush=True)
