#!/usr/bin/env python3
"""Latency/throughput benchmark for a running aisnekbox server.

Fires a configurable number of ``POST /eval`` requests at a target concurrency
and reports throughput and latency percentiles. Intended to be run against a
live container (``docker compose up``), e.g.::

    python scripts/benchmark.py --url http://localhost:8060 --requests 200 --concurrency 8

It deliberately depends only on the standard library so it can run anywhere
without installing the package.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

DEFAULT_CODE = "print(sum(range(10000)))"


def _one_request(url: str, payload: bytes, timeout: float) -> tuple[int, float]:
    """Send a single /eval request; return (status_code, latency_seconds)."""
    req = urllib.request.Request(  # noqa: S310 - fixed http(s) URL from CLI arg
        url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
    )
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            resp.read()
            status = resp.status
    except urllib.error.HTTPError as exc:
        status = exc.code
    except (urllib.error.URLError, TimeoutError):
        status = 0
    return status, time.perf_counter() - start


def run(url: str, total: int, concurrency: int, code: str, timeout: float) -> int:
    endpoint = url.rstrip("/") + "/eval"
    payload = json.dumps({"input": code}).encode("utf-8")

    latencies: list[float] = []
    statuses: list[int] = []
    wall_start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(_one_request, endpoint, payload, timeout) for _ in range(total)]
        for fut in futures:
            status, latency = fut.result()
            statuses.append(status)
            latencies.append(latency)
    wall = time.perf_counter() - wall_start

    ok = sum(1 for s in statuses if s == 200)
    rejected = sum(1 for s in statuses if s == 429)
    failed = sum(1 for s in statuses if s not in (200, 429))
    latencies.sort()

    def pct(p: float) -> float:
        if not latencies:
            return 0.0
        idx = min(len(latencies) - 1, int(p / 100.0 * len(latencies)))
        return latencies[idx] * 1000.0

    print(f"target           : {endpoint}")
    print(f"requests         : {total} (concurrency {concurrency})")
    print(f"wall time        : {wall:.2f}s")
    print(f"throughput       : {total / wall:.1f} req/s")
    print(f"status 200/429/x : {ok}/{rejected}/{failed}")
    if latencies:
        print(f"latency mean     : {statistics.mean(latencies) * 1000:.1f} ms")
        print(f"latency p50/p95/p99: {pct(50):.1f}/{pct(95):.1f}/{pct(99):.1f} ms")
    return 0 if failed == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:8060", help="Base server URL.")
    parser.add_argument("--requests", type=int, default=100, help="Total requests to send.")
    parser.add_argument("--concurrency", type=int, default=8, help="Concurrent workers.")
    parser.add_argument("--code", default=DEFAULT_CODE, help="Python source to evaluate.")
    parser.add_argument("--timeout", type=float, default=30.0, help="Per-request timeout (s).")
    args = parser.parse_args()
    return run(args.url, args.requests, args.concurrency, args.code, args.timeout)


if __name__ == "__main__":
    raise SystemExit(main())
