#!/usr/bin/env python3
"""Throughput sweep: concurrency x prefix length, in tokens.

Talks to vLLM's /v1/completions endpoint with `prompt` as a list of integer
token IDs (vLLM accepts that directly), so we don't need a tokenizer or any
text calibration. Each request gets a unique random sequence of token IDs
(distinct per-request seed) so the prefix cache cannot help across requests.

Generation length is sampled per-request uniformly in
[OUTPUT_TOKENS_MIN, OUTPUT_TOKENS_MAX], pinned via min_tokens=max_tokens and
ignore_eos=True so the model emits exactly that many tokens regardless of
content. Prompt and response are gibberish — we only care about throughput.

Each (concurrency, prefix_tokens) cell submits enough requests so the total
prompt+output tokens crosses TOTAL_TOKENS_BUDGET (default 2**20 = ~1M). For
high concurrency / short prefixes that's many small rounds; for long prefixes
it's a handful of large requests. Reports total generation throughput
(tok/s) per cell after a warmup pass.
"""
import json, math, time, urllib.request, concurrent.futures as cf, random, sys

URL = "http://localhost:8000/v1/completions"   # bypass Cloudflare's 100s edge timeout
MODEL = "openai/gpt-oss-20b"

OUTPUT_TOKENS_MIN = 128
OUTPUT_TOKENS_MAX = 1024
GEN_TOKENS_BUDGET = 2 ** 17      # power of 2, 131072 generation tokens per cell

PREFIX_LENGTHS = [1, 1024, 16384, 98304]
CONCURRENCIES = [1, 4, 16, 64, 256]

# gpt-oss uses the o200k_harmony tokenizer (~201k vocab). We pick from a
# middle range to dodge specials and reserved IDs. Using a small range is
# fine — vLLM still has to attend over the whole prefix.
TOK_LO, TOK_HI = 1000, 100_000


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
    t0 = time.perf_counter()
    req = urllib.request.Request(
        URL,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "curl/8.5.0"},
    )
    with urllib.request.urlopen(req, timeout=600) as r:
        data = json.loads(r.read())
    dt = time.perf_counter() - t0
    u = data["usage"]
    return dt, u["prompt_tokens"], u["completion_tokens"]


def plan_requests(N, prefix_tokens, seed_base):
    """Return list of (prompt_ids, output_tokens) for one cell.

    Targets GEN_TOKENS_BUDGET total completion tokens per cell, but always
    sends at least N requests so the engine has a full first batch.
    """
    out_rng = random.Random(seed_base)
    avg_out = (OUTPUT_TOKENS_MIN + OUTPUT_TOKENS_MAX) // 2
    by_budget = math.ceil(GEN_TOKENS_BUDGET / avg_out)
    n_requests = max(N, by_budget)
    plan = []
    for i in range(n_requests):
        out_tok = out_rng.randint(OUTPUT_TOKENS_MIN, OUTPUT_TOKENS_MAX)
        prompt = random_token_ids(prefix_tokens, seed=seed_base * 100_003 + i)
        plan.append((prompt, out_tok))
    return plan


def sweep_cell(N, prefix_tokens, seed_base):
    plan = plan_requests(N, prefix_tokens, seed_base)
    t0 = time.perf_counter()
    with cf.ThreadPoolExecutor(max_workers=N) as ex:
        futs = [ex.submit(one, p, k) for (p, k) in plan]
        results = [f.result() for f in cf.as_completed(futs)]
    wall = time.perf_counter() - t0
    c_tok = sum(r[2] for r in results)
    p_tok = sum(r[1] for r in results)
    return c_tok / wall, len(plan), p_tok, c_tok, wall


def warmup():
    """One pass at modest concurrency for each prefix length to settle CUDA graphs / batch shapes."""
    for L in PREFIX_LENGTHS:
        # min(8, max(CONCURRENCIES)) — keep warmup quick at long prefixes
        Nw = min(8, max(CONCURRENCIES))
        prompts = [(random_token_ids(L, seed=99_000 + i), 128) for i in range(Nw)]
        with cf.ThreadPoolExecutor(max_workers=Nw) as ex:
            list(ex.map(lambda pk: one(pk[0], pk[1]), prompts))
        print(f"#   warmup done for prefix={L}", file=sys.stderr)


if __name__ == "__main__":
    print(f"# Config: GEN_TOKENS_BUDGET={GEN_TOKENS_BUDGET}, "
          f"output_tokens~U[{OUTPUT_TOKENS_MIN},{OUTPUT_TOKENS_MAX}]",
          file=sys.stderr)
    print("# Warming up engine…", file=sys.stderr)
    warmup()

    header = "prefix \\ concurrency  | " + " | ".join(f"{N:>6d}" for N in CONCURRENCIES)
    print(header)
    print("-" * len(header))

    diagnostics = []
    seed_base = 1
    for L in PREFIX_LENGTHS:
        row = [f"{L:>20d}"]
        for N in CONCURRENCIES:
            tps, n_req, p_tok, c_tok, wall = sweep_cell(N, L, seed_base)
            seed_base += n_req + 7
            diagnostics.append((L, N, n_req, p_tok, c_tok, wall, tps))
            row.append(f"{tps:>6.0f}")
            print(f"#   L={L:>5} N={N:>3}: {n_req:>4} reqs, "
                  f"p={p_tok:>8d}, c={c_tok:>7d}, wall={wall:>6.1f}s, "
                  f"out_tps={tps:>6.1f}", file=sys.stderr)
        print("  | ".join(row))
