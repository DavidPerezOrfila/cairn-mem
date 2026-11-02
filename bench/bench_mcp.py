"""Latencia de las tool calls MCP en proceso (sin arranque de Python).

Uso: python bench/bench_mcp.py [--reps 20] [--json]
Mide search/save/context sobre 10k registros con el mismo sembrado que la CLI.
"""

import argparse
import json
import os
import tempfile
import time
from pathlib import Path

from bench_cli import _seed, _stats

from cairn_mem.mcp import Server

SLO_MS = 50
COUNT = 10000


def _call(server: Server, name: str, arguments: dict) -> None:
    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
    )
    if response["result"].get("isError"):
        raise RuntimeError(response["result"]["content"][0]["text"])


def bench(reps: int) -> dict:
    root = Path(tempfile.mkdtemp(prefix="cairn-bench-mcp-")) / ".cairn"
    root.mkdir(parents=True)
    _seed(root, COUNT)
    os.environ["CAIRN_DIR"] = str(root)
    server = Server()
    server.store()  # pagar el rebuild fuera de la medición

    timings = {"search": [], "save": [], "context": []}
    for index in range(reps):
        start = time.perf_counter()
        _call(server, "search", {"query": "oauth", "limit": 5})
        timings["search"].append((time.perf_counter() - start) * 1000)

        start = time.perf_counter()
        _call(server, "save", {"kind": "fact", "title": f"bench {index}", "body": "b"})
        timings["save"].append((time.perf_counter() - start) * 1000)

        start = time.perf_counter()
        _call(server, "context", {})
        timings["context"].append((time.perf_counter() - start) * 1000)

    return {"records": COUNT, **{key: _stats(value) for key, value in timings.items()}}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reps", type=int, default=20)
    parser.add_argument("--json", action="store_true")
    ns = parser.parse_args(argv)
    result = bench(ns.reps)
    if ns.json:
        print(json.dumps(result, indent=2))
        return 0
    print(f"{result['records']} registros (tool call en proceso)")
    for key in ("search", "save", "context"):
        stats = result[key]
        print(
            f"  {key:<8} p50 {stats['p50_ms']:>6.1f} ms  p95 {stats['p95_ms']:>6.1f} ms"
        )
    worst = max(result[key]["p95_ms"] for key in ("search", "save", "context"))
    print(f"  SLO (p95 < {SLO_MS} ms): {'OK' if worst < SLO_MS else 'FALLA'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
