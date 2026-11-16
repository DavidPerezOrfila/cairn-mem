"""Trigger de anchor_cache (PLAN.md 5): coste marginal de los anclas en `save`.

`save` regenera el L0, y el L0 solo hashea los anclas de las memorias que caben en
el presupuesto de 3000 caracteres. `check` hashea el resto, pero no está en la ruta
de escritura. Esta medición pone los anclas en las memorias más recientes (las que
sí caben) y compara el mismo store con y sin anclas.

Uso: python bench/bench_anchors.py [--reps 20] [--json]

Mide; no decide. El cache entre comandos está cerrado por la garantía de stale
(`docs/DECISIONS.md`, 2026-11-16): la identidad `(size, mtime_ns)` llega tarde en
NTFS y verificar por contenido vuelve a leer el fichero. Este bench vigila el coste
del render paralelo que sí se aplicó.
"""

import argparse
import json
import statistics
import tempfile
import time
from contextlib import closing
from pathlib import Path

from cairn_mem.anchor import file_hash
from cairn_mem.store import Store

KINDS = ("decision", "convention", "gotcha", "fact")
SCENARIOS = ((200, 10), (200, 100), (200, 256))


def _seed(root: Path, count: int, anchors: int, anchor_kb: int) -> None:
    """Anclas en las últimas memorias (ts más alto = primero en el L0)."""
    lines = []
    for index in range(count):
        event = {
            "op": "save",
            "id": f"{index:012x}",
            "ts": 1_700_000_000_000_000_000 + index,
            "kind": KINDS[index % len(KINDS)],
            "title": f"memoria {index}",
            "body": f"detalle sintetico {index}",
        }
        if index >= count - anchors:
            name = f"ancla_{index}.txt"
            size = anchor_kb * 1024
            data = (f"linea {index}\n" * (size // 10 + 1))[:size]
            (root.parent / name).write_text(data, encoding="utf-8", newline="\n")
            event["anchor_path"] = name
            event["anchor_hash"] = file_hash(root.parent / name)
        lines.append(json.dumps(event, ensure_ascii=False))
    (root / "events.jsonl").write_text(
        "\n".join(lines) + "\n", encoding="utf-8", newline="\n"
    )


def measure(root: Path, count: int, anchors: int, anchor_kb: int, reps: int) -> dict:
    _seed(root, count, anchors, anchor_kb)
    render = []
    save = []
    with closing(Store(str(root))) as store:
        store.write_l0()  # primera pasada fuera de la medida
        for index in range(reps):
            start = time.perf_counter()
            store.write_l0()
            render.append((time.perf_counter() - start) * 1000)
            start = time.perf_counter()
            store.save(kind="fact", title=f"bench {index}", body="bench")
            save.append((time.perf_counter() - start) * 1000)
    return {
        "memories": count,
        "anchors": anchors,
        "anchor_kb": anchor_kb,
        "render_p50_ms": round(statistics.median(render), 1),
        "save_p50_ms": round(statistics.median(save), 1),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reps", type=int, default=20)
    parser.add_argument("--count", type=int, default=10_000)
    parser.add_argument("--json", action="store_true")
    ns = parser.parse_args(argv)

    results = []
    with tempfile.TemporaryDirectory(prefix="cairn-anchors-") as tmp:
        base = Path(tmp) / "base" / ".cairn"
        base.mkdir(parents=True)
        baseline = measure(base, ns.count, 0, 0, ns.reps)
        results.append(baseline)
        for anchors, kb in SCENARIOS:
            root = Path(tmp) / f"a{anchors}-{kb}" / ".cairn"
            root.mkdir(parents=True)
            results.append(measure(root, ns.count, anchors, kb, ns.reps))

    for result in results[1:]:
        result["marginal_save_ms"] = round(
            result["save_p50_ms"] - baseline["save_p50_ms"], 1
        )

    if ns.json:
        print(json.dumps(results, indent=2))
    else:
        print(f"anchor_cache trigger: {ns.count} memorias, p50 en proceso\n")
        print(f"{'anclas':>7}{'KiB':>6}{'L0 ms':>8}{'save ms':>9}{'marginal':>10}")
        for result in results:
            marginal = result.get("marginal_save_ms", 0.0)
            print(
                f"{result['anchors']:>7}{result['anchor_kb']:>6}"
                f"{result['render_p50_ms']:>8.1f}{result['save_p50_ms']:>9.1f}"
                f"{marginal:>10.1f}"
            )
        worst = max(result["marginal_save_ms"] for result in results[1:])
        print(f"\npeor marginal: {worst:.1f} ms sobre la línea base")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
