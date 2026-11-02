"""Medición end-to-end de la CLI: p50/p95 de search y save con 1k y 10k registros.

Uso: python bench/bench_cli.py [--reps 20] [--json]
El sembrado escribe el JSONL directamente y deja que Store lo reconstruya;
así se mide la CLI real sin pagar O(n²) durante el montaje.
"""

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from cairn_mem.store import Store

KINDS = ("decision", "convention", "gotcha", "fact")
SEARCH_SLO_MS = 150
SAVE_SLO_MS = 200
SIZES = (1000, 10000)


def _seed(root: Path, count: int) -> None:
    lines = []
    for i in range(count):
        title = f"memoria {i} oauth" if i % 10 == 0 else f"memoria {i}"
        event = {
            "op": "save",
            "id": f"{i:012x}",
            "ts": 1_700_000_000_000_000_000 + i,
            "kind": KINDS[i % 4],
            "title": title,
            "body": f"detalle sintetico {i}",
        }
        lines.append(json.dumps(event, ensure_ascii=False))
    (root / "events.jsonl").write_text(
        "\n".join(lines) + "\n", encoding="utf-8", newline="\n"
    )


def _stats(values: list[float]) -> dict:
    ordered = sorted(values)
    return {
        "p50_ms": round(statistics.median(ordered), 1),
        "p95_ms": round(ordered[max(0, int(len(ordered) * 0.95) - 1)], 1),
        "min_ms": round(ordered[0], 1),
        "max_ms": round(ordered[-1], 1),
    }


def _cli_ms(root: Path, args: list[str], reps: int) -> list[float]:
    env = dict(os.environ, CAIRN_DIR=str(root))
    times = []
    for _ in range(reps):
        start = time.perf_counter()
        subprocess.run(
            [sys.executable, "-m", "cairn_mem.cli", *args],
            env=env,
            capture_output=True,
            check=True,
        )
        times.append((time.perf_counter() - start) * 1000)
    return times


def bench_size(count: int, reps: int) -> dict:
    root = Path(tempfile.mkdtemp(prefix=f"cairn-bench-{count}-")) / ".cairn"
    root.mkdir(parents=True)

    start = time.perf_counter()
    _seed(root, count)
    store = Store(str(root))
    rebuild_ms = (time.perf_counter() - start) * 1000

    searches = _cli_ms(root, ["search", "oauth", "--limit", "5"], reps)
    saves = _cli_ms(
        root,
        ["save", "--kind", "fact", "--title", "bench", "--body", "bench"],
        reps,
    )

    store = Store(str(root))
    internal = []
    for _ in range(20):
        start = time.perf_counter()
        store.search("oauth")
        internal.append((time.perf_counter() - start) * 1000)

    return {
        "records": count,
        "rebuild_ms": round(rebuild_ms, 1),
        "search": _stats(searches),
        "save": _stats(saves),
        "internal_search": _stats(internal),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reps", type=int, default=20)
    parser.add_argument("--json", action="store_true")
    ns = parser.parse_args(argv)
    results = [bench_size(count, ns.reps) for count in SIZES]
    if ns.json:
        print(json.dumps(results, indent=2))
        return 0
    for result in results:
        print(f"{result['records']} registros")
        print(f"  rebuild:        {result['rebuild_ms']:>8.1f} ms")
        for key, label in (
            ("search", "search e2e"),
            ("save", "save e2e"),
            ("internal_search", "search interno"),
        ):
            stats = result[key]
            print(
                f"  {label:<15} p50 {stats['p50_ms']:>7.1f} ms"
                f"  p95 {stats['p95_ms']:>7.1f} ms"
            )
        verdict = (
            result["search"]["p95_ms"] < SEARCH_SLO_MS
            and result["save"]["p95_ms"] < SAVE_SLO_MS
        )
        print(
            f"  SLO (search<{SEARCH_SLO_MS}, save<{SAVE_SLO_MS}): "
            f"{'OK' if verdict else 'FALLA'}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
