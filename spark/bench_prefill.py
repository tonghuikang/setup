#!/usr/bin/env python3
"""Measure prefill time at each prefix length.

For each L in PREFIX_LENGTHS, sends a request with output_tokens=1 using a
fresh random prefix (cold for the prefix cache), and reports wall time.
That wall time is dominated by prefill — one decode step is ~tens of ms,
negligible against any non-trivial prefill.

Run after the main benchmark; both can't share GPU time.
"""
import json, time, urllib.request, random, sys

URL = "http://localhost:8000/v1/completions"
MODEL = "openai/gpt-oss-20b"

PREFIX_LENGTHS = [1, 4096, 32768, 98304]
TOK_LO, TOK_HI = 1000, 100_000


def random_token_ids(n_tokens, seed):
    rng = random.Random(seed)
    return [rng.randint(TOK_LO, TOK_HI) for _ in range(n_tokens)]


def probe(prompt_ids):
    body = json.dumps({
        "model": MODEL,
        "prompt": prompt_ids,
        "max_tokens": 1,
        "min_tokens": 1,
        "ignore_eos": True,
        "temperature": 0.0,
    }).encode()
    req = urllib.request.Request(
        URL,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "curl/8.5.0"},
    )
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=600) as r:
        json.loads(r.read())
    return time.perf_counter() - t0


if __name__ == "__main__":
    # Quick warmup so first probe doesn't carry CUDA-graph capture cost.
    probe(random_token_ids(64, seed=88_000))

    print(f"{'prefix':>8}  {'wall_s':>7}")
    for L in PREFIX_LENGTHS:
        prompt = random_token_ids(L, seed=77_000 + L)
        dt = probe(prompt)
        print(f"{L:>8d}  {dt:>7.2f}")
