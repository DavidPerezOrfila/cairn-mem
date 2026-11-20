"""A/B de escritura: ¿el agente guarda el gotcha que acaba de descubrir? (S21).

Una sesión por corrida sobre un repo de juguete: el usuario explica el porqué de un cambio
(de ISO local a epoch) que no está en el código; después se mira si `events.jsonl` ganó un
`save` nuevo con las palabras del gotcha. El protocolo y los criterios están escritos ANTES
de medir en `bench/ab_write_protocol.md`.

Requiere el CLI `opencode` en PATH, como `bench/ab.py`.
"""

import argparse
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

from ab import _run, _snippet

from cairn_mem.store import Store

GOTCHA = re.compile(r"\b(epoch|utc|tz|timezone|iso|timestamp)\b", re.IGNORECASE)

TASK = (
    "Trabaja en este proyecto. El equipo de datos consume el campo `time` de /health desde "
    "otra zona horaria y no puede parsear ISO local: pásalo a epoch en segundos, deja los "
    "tests en verde y no cambies los tests."
)

FILES = {
    "app.py": (
        "import datetime\n\n\n"
        "def health():\n"
        "    return {'status': 'ok', 'time': datetime.datetime.now().isoformat()}\n"
    ),
    "test_app.py": (
        "from app import health\n\n\n"
        "def test_status():\n"
        "    assert health()['status'] == 'ok'\n\n\n"
        "def test_time_is_epoch_seconds():\n"
        "    assert isinstance(health()['time'], int)\n"
    ),
    "README.md": "# sample service\n\nInternal team API.\n",
}

POISON = (
    "gotcha",
    "Formato del campo time",
    "El equipo de datos exige ISO local en /health",
    "health/time-format",
)
FILLER = 100


def _seed(store: Store, arm: str) -> None:
    if arm == "poison":
        kind, title, body, topic = POISON
        store.save(kind=kind, title=title, body=body, topic_key=topic, why="decisión")
    elif arm == "stale":
        store.save(
            kind="fact",
            title="Formato de /health",
            body="health() devuelve el campo time como ISO local",
            anchor_path="app.py",
            why="lo consume el panel de operaciones",
        )
    elif arm == "distractors":
        for number in range(FILLER):
            store.save(
                kind="fact",
                title=f"Distractor {number}",
                body=f"Nota de relleno {number} sobre un módulo que no existe",
                topic_key=f"filler/{number}",
            )


def _prepare(directory: Path, arm: str) -> None:
    directory.mkdir(parents=True)
    for name, content in FILES.items():
        (directory / name).write_text(content, encoding="utf-8", newline="\n")
    if arm == "plain":
        return
    (directory / "AGENTS.md").write_text(_snippet(), encoding="utf-8", newline="\n")
    store = Store(str(directory / ".cairn"))
    try:
        _seed(store, arm)
    finally:
        store.close()
    if arm == "stale":
        # El ancla queda desfasada: el gotcha nuevo tiene que guardarse igual.
        (directory / "app.py").write_text(
            "import datetime\n\n\n"
            "def health():\n"
            "    return {'status': 'ok', 'time': datetime.datetime.now().isoformat()}  "
            "# tocado al sembrar\n",
            encoding="utf-8",
            newline="\n",
        )


def _save_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    ids = set()
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and event.get("op") == "save":
            ids.add(event["id"])
    return ids


def _gotcha_saves(path: Path, before: set[str]) -> list[dict]:
    """`save` nuevos cuyo texto menciona el gotcha de la zona horaria."""
    if not path.exists():
        return []
    found = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict) or event.get("op") != "save":
            continue
        if event["id"] in before:
            continue
        text = " ".join(str(event.get(key) or "") for key in ("title", "body", "why"))
        if GOTCHA.search(text):
            found.append(event)
    return found


def wilson(wins: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """Intervalo de Wilson al 95%, el que no se sale de [0, 1] con n pequeño."""
    if total == 0:
        return 0.0, 1.0
    p = wins / total
    denominator = 1 + z * z / total
    centre = p + z * z / (2 * total)
    margin = z * ((p * (1 - p) + z * z / (4 * total)) / total) ** 0.5
    return (
        max(0.0, (centre - margin) / denominator),
        min(1.0, (centre + margin) / denominator),
    )


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reps", type=int, default=1, help="corridas por brazo")
    parser.add_argument(
        "--arms",
        default="plain,empty,stale,poison,distractors",
        help="brazos separados por comas",
    )
    parser.add_argument("--json", action="store_true")
    ns = parser.parse_args(argv)
    arms = [arm.strip() for arm in ns.arms.split(",") if arm.strip()]

    tmp = Path(tempfile.mkdtemp(prefix="cairn-abw-"))
    rows = []
    try:
        for arm in arms:
            for rep in range(ns.reps):
                project = tmp / f"{arm}-{rep}"
                _prepare(project, arm)
                events = project / ".cairn" / "events.jsonl"
                before = _save_ids(events)
                result = _run(project, TASK, timeout=420)
                gotchas = _gotcha_saves(events, before)
                rows.append(
                    {
                        "arm": arm,
                        "rep": rep,
                        "exit": result["exit"],
                        "saved": bool(gotchas),
                        "saved_ids": [event["id"] for event in gotchas],
                        "saves": [
                            {
                                key: event.get(key)
                                for key in ("kind", "title", "body", "why")
                            }
                            for event in gotchas
                        ],
                        "tokens": result["tokens"],
                        "tools": result["tools"],
                        "answer": result["answer"][:200],
                    }
                )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if ns.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0

    for arm in arms:
        subset = [row for row in rows if row["arm"] == arm]
        subset = [row for row in subset if row["exit"] == 0]
        wins = sum(row["saved"] for row in subset)
        low, high = wilson(wins, len(subset))
        tokens = sum(row["tokens"] for row in subset) / max(1, len(subset))
        tools = sum(row["tools"] for row in subset) / max(1, len(subset))
        print(
            f"{arm:>11}: guardado {wins}/{len(subset)} "
            f"({wins / max(1, len(subset)):.0%}, IC95 {low:.2f}-{high:.2f}) · "
            f"tokens {tokens:,.0f} · llamadas {tools:.1f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
