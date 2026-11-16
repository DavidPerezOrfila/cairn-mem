"""Latencia de las tool calls MCP en proceso (sin arranque de Python).

Uso: python bench/bench_mcp.py [--reps 20] [--json]
Mide search/save/context sobre 10k registros con el mismo sembrado que la CLI.
"""

import argparse
import json
import os
import tempfile
import time
from contextlib import closing
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
    with tempfile.TemporaryDirectory(prefix="cairn-bench-mcp-") as tmp:
        root = Path(tmp) / ".cairn"
        root.mkdir(parents=True)
        _seed(root, COUNT)
        previous = os.environ.get("CAIRN_DIR")
        os.environ["CAIRN_DIR"] = str(root)
        try:
            server = Server()
            # pagar el rebuild fuera de la medición
            with closing(server.store()):
                timings = {"search": [], "save": [], "context": []}
                for index in range(reps):
                    start = time.perf_counter()
                    _call(server, "search", {"query": "oauth", "limit": 5})
                    timings["search"].append((time.perf_counter() - start) * 1000)

                    start = time.perf_counter()
                    _call(
                        server,
                        "save",
                        {"kind": "fact", "title": f"bench {index}", "body": "b"},
                    )
                    timings["save"].append((time.perf_counter() - start) * 1000)

                    start = time.perf_counter()
                    _call(server, "context", {})
                    timings["context"].append((time.perf_counter() - start) * 1000)
        finally:
            if previous is None:
                os.environ.pop("CAIRN_DIR", None)
            else:
                os.environ["CAIRN_DIR"] = previous

        return {"records": COUNT, **{k: _stats(v) for k, v in timings.items()}}


def slo_ok(result: dict) -> bool:
    return all(result[key]["p95_ms"] < SLO_MS for key in ("search", "save", "context"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reps", type=int, default=20)
    parser.add_argument("--json", action="store_true")
    ns = parser.parse_args(argv)
    result = bench(ns.reps)
    ok = slo_ok(result)
    if ns.json:
        print(json.dumps(result, indent=2))
        return 0 if ok else 1
    print(f"{result['records']} registros (tool call en proceso)")
    for key in ("search", "save", "context"):
        stats = result[key]
        print(
            f"  {key:<8} p50 {stats['p50_ms']:>6.1f} ms  p95 {stats['p95_ms']:>6.1f} ms"
        )
    print(f"  SLO (p95 < {SLO_MS} ms): {'OK' if ok else 'FALLA'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
