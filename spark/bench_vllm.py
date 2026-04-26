#!/usr/bin/env python3
"""Throughput sweep: concurrency x prefix length, in tokens.

Talks to vLLM's /v1/completions endpoint with `prompt` as a list of integer
token IDs (vLLM accepts that directly), so we don't need a tokenizer or any
text calibration.

Each (N, prefix_tokens) cell sends N concurrent requests that all share the
same random prefix of `prefix_tokens` token IDs — i.e. shared-context
workload (long system prompt / document), where vLLM's prefix cache absorbs
the prefill cost after the first request and the cell measures decode
throughput at concurrency N.

Generation length is sampled per-request uniformly in
[OUTPUT_TOKENS_MIN, OUTPUT_TOKENS_MAX], pinned via min_tokens=max_tokens and
ignore_eos=True so the model emits exactly that many tokens regardless of
content. Prompts/completions are gibberish — only throughput matters.

A single warmup pass (8 concurrent, 64-token shared prefix, 16 output
tokens) runs once at the start, before any timed cell.
"""
import json, time, urllib.request, concurrent.futures as cf, random, sys

URL = "http://localhost:8000/v1/completions"   # bypass Cloudflare's 100s edge timeout
MODEL = "openai/gpt-oss-20b"

OUTPUT_TOKENS_MIN = 128
OUTPUT_TOKENS_MAX = 1024

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

    All N requests share the same prefix (one prefix per prefix-length).
    This lets vLLM's prefix cache absorb the prefill cost after the first
    request — appropriate for shared-context workloads (long system prompt,
    shared document, …).
    """
    out_rng = random.Random(seed_base)
    shared_prefix = random_token_ids(prefix_tokens, seed=seed_base)
    plan = []
    for _ in range(N):
        out_tok = out_rng.randint(OUTPUT_TOKENS_MIN, OUTPUT_TOKENS_MAX)
        plan.append((shared_prefix, out_tok))
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
    """One short pass to settle engine state before any timed cell.

    16-token output, single shared 64-token prefix replicated across the
    warmup batch.
    """
    Nw = min(8, max(CONCURRENCIES))
    shared_prefix = random_token_ids(64, seed=99_000)
    prompts = [(shared_prefix, 16) for _ in range(Nw)]
    with cf.ThreadPoolExecutor(max_workers=Nw) as ex:
        list(ex.map(lambda pk: one(pk[0], pk[1]), prompts))
    print(f"#   warmup done", file=sys.stderr)


if __name__ == "__main__":
    print(f"# Config: output_tokens~U[{OUTPUT_TOKENS_MIN},{OUTPUT_TOKENS_MAX}], "
          f"shared prefix per cell",
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
