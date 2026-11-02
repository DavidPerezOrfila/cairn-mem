"""A/B pareado y orientativo: sin memoria vs con memoria.

Requiere el CLI `opencode` en PATH. Ver bench/ab_protocol.md.
"""

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from cairn_mem.store import Store

ROOT = Path(__file__).resolve().parents[1]
SNIPPET = ROOT / "docs" / "AGENT_SNIPPET.md"

FACTS = (
    (
        "decision",
        "Rate limit publico",
        "El rate limit del endpoint publico es 60 peticiones por minuto",
    ),
    (
        "convention",
        "Deploy a produccion",
        "El deploy a produccion se hace con make deploy-prod",
    ),
    (
        "convention",
        "Tests rapidos",
        "Los tests rapidos se lanzan con pytest -q -m 'not slow'",
    ),
    (
        "decision",
        "Migraciones de base de datos",
        "Las migraciones se gestionan con alembic",
    ),
    ("convention", "Rama de staging", "La rama de staging se llama release/staging"),
    ("convention", "Zona horaria", "El proyecto usa la zona horaria Europe/Madrid"),
    (
        "decision",
        "Feature flag del checkout",
        "El feature flag del checkout nuevo es NEW_CHECKOUT",
    ),
    (
        "decision",
        "Gestor de secretos",
        "El equipo usa bitwarden como gestor de secretos",
    ),
)

TASKS = (
    ("¿Cuantas peticiones por minuto permite el rate limit publico?", "60"),
    ("¿Que comando se usa para desplegar a produccion?", "make deploy-prod"),
    ("¿Que comando lanza los tests rapidos?", "pytest -q -m"),
    ("¿Que herramienta gestiona las migraciones de base de datos?", "alembic"),
    ("¿Como se llama la rama de staging?", "release/staging"),
    ("¿Que zona horaria usa el proyecto?", "Europe/Madrid"),
    ("¿Que clave tiene el feature flag del checkout nuevo?", "NEW_CHECKOUT"),
    ("¿Que gestor de secretos usa el equipo?", "bitwarden"),
)

FILES = {
    "app.py": (
        "import os\n\n"
        "RATE_LIMIT = os.environ['RATE_LIMIT']\n"
        "TIMEZONE = os.environ['TZ']\n\n\n"
        "def health():\n"
        "    return {'status': 'ok'}\n"
    ),
    "config.py": (
        "import os\n\n"
        "FEATURE_FLAGS = os.environ['FEATURE_FLAGS'].split(',')\n"
        "SECRETS_BACKEND = os.environ['SECRETS_BACKEND']\n"
    ),
    "Makefile": "lint:\n\truff check .\n\nformat:\n\truff format .\n",
    "README.md": "# servicio de ejemplo\n\nAPI interna del equipo.\n",
}


def _snippet() -> str:
    lines = SNIPPET.read_text(encoding="utf-8").splitlines()[3:]
    while lines and lines[-1].strip().startswith("```"):
        lines.pop()
    return "\n".join(lines).strip() + "\n"


def _prepare(directory: Path, arm: str) -> None:
    directory.mkdir(parents=True)
    for name, content in FILES.items():
        (directory / name).write_text(content, encoding="utf-8", newline="\n")
    if arm == "sin":
        return
    (directory / "AGENTS.md").write_text(_snippet(), encoding="utf-8", newline="\n")
    store = Store(str(directory / ".cairn"))
    for kind, title, body in FACTS:
        store.save(kind=kind, title=title, body=body, why="convencion del equipo")


def _run(directory: Path, question: str) -> dict:
    proc = subprocess.run(
        [
            "opencode",
            "run",
            "--auto",
            "--format",
            "json",
            f"Trabaja en este proyecto. Responde solo con el dato pedido, sin explicar. {question}",
        ],
        cwd=directory,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=240,
    )
    text = []
    tokens = 0
    tools = 0
    for line in proc.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        part = event.get("part") or {}
        if part.get("type") == "text":
            text.append(part.get("text", ""))
        elif part.get("type") in ("tool", "tool_use"):
            tools += 1
        if part.get("type") == "step-finish":
            usage = part.get("tokens") or {}
            tokens += usage.get("input", 0) + usage.get("output", 0)
    return {"answer": " ".join(text).strip(), "tokens": tokens, "tools": tools}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reps", type=int, default=2)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--tasks", type=int, default=len(TASKS))
    ns = parser.parse_args(argv)

    tmp = Path(tempfile.mkdtemp(prefix="cairn-ab-"))
    rows = []
    try:
        for rep in range(ns.reps):
            for arm in ("sin", "con"):
                for question, expected in TASKS[: ns.tasks]:
                    project = tmp / f"{arm}-{rep}-{len(rows)}"
                    _prepare(project, arm)
                    result = _run(project, question)
                    result.update(
                        rep=rep,
                        arm=arm,
                        question=question,
                        expected=expected,
                        success=expected.lower() in result["answer"].lower(),
                    )
                    rows.append(result)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if ns.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0

    for arm in ("sin", "con"):
        subset = [row for row in rows if row["arm"] == arm]
        wins = sum(row["success"] for row in subset)
        tokens = sum(row["tokens"] for row in subset) / len(subset)
        tools = sum(row["tools"] for row in subset) / len(subset)
        print(
            f"{arm:>3}: exito {wins}/{len(subset)} · "
            f"tokens {tokens:,.0f} · llamadas {tools:.1f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
