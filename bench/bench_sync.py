"""Latencia de sync incremental: dos Store alternando sobre 10k registros.

Uso: python bench/bench_sync.py [--reps 40] [--json]
Cada vuelta escribe con un Store y lee con el otro. Antes de S7 esa lectura
pagaba un rebuild completo (~236 ms de mediana según la auditoría); ahora solo
aplica la cola nueva.
"""

import argparse
import json
import tempfile
import time
from pathlib import Path

from bench_cli import _seed, _stats

from cairn_mem.store import Store

SLO_MS = 50
COUNT = 10000


def bench(reps: int) -> dict:
    root = Path(tempfile.mkdtemp(prefix="cairn-bench-sync-")) / ".cairn"
    root.mkdir(parents=True)
    _seed(root, COUNT)
    writers = [Store(str(root)), Store(str(root))]

    timings = {"save": [], "search": []}
    for index in range(reps):
        start = time.perf_counter()
        writers[index % 2].save(kind="fact", title=f"sync {index} oauth", body="b")
        timings["save"].append((time.perf_counter() - start) * 1000)

        start = time.perf_counter()
        writers[(index + 1) % 2].search("oauth", limit=5)
        timings["search"].append((time.perf_counter() - start) * 1000)

    return {"records": COUNT, **{key: _stats(value) for key, value in timings.items()}}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reps", type=int, default=40)
    parser.add_argument("--json", action="store_true")
    ns = parser.parse_args(argv)
    result = bench(ns.reps)
    if ns.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"{result['records']} registros, 2 escritores")
        for key, label in (("save", "save"), ("search", "search")):
            stats = result[key]
            print(
                f"  {label:<8} p50 {stats['p50_ms']:>8.1f} ms"
                f"  p95 {stats['p95_ms']:>8.1f} ms"
                f"  max {stats['max_ms']:>8.1f} ms"
            )
    verdict = all(result[key]["p95_ms"] < SLO_MS for key in ("save", "search"))
    print(f"  SLO (<{SLO_MS} ms p95): {'OK' if verdict else 'FALLA'}")
    return 0 if verdict else 1


if __name__ == "__main__":
    raise SystemExit(main())
