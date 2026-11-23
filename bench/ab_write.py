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
import subprocess
import sys
import tempfile
from pathlib import Path

from ab import _run, _snippet

from cairn_mem.setup import install_hook
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

# Round 4 (S28 remainder): el brazo `stop` bajo claude-code. El texto es el de la ronda 3
# (assets/stop/index.ts), congelado en el protocolo; lo fija tests/test_ab_write.py.
CC_NUDGE = (
    "Al cerrar: si esta conversación te dio una razón que no está en el código (por qué el "
    "usuario quiere el cambio, una restricción, quién consume el dato), guárdala ahora en la "
    "memoria del proyecto con `cairn save`, con ese porqué en `--why` y un `--topic` "
    "estable. Una sola memoria. Si no hay ninguna razón así, no hagas nada."
)

CC_HOOK = '''"""Stop hook de Claude Code (round 4, S28): un solo empujón por sesión.

Bloquea la primera parada de una sesión que no ha guardado: Claude continúa con la razón
como instrucción. La línea base de saves se fija al instalar el hook (el equivalente al
`before` del plugin de OpenCode); en Windows el comando lo lanza Git Bash.
"""
import json
import sys
from pathlib import Path

NUDGE = "@NUDGE@"


def _saves(directory: Path) -> int:
    try:
        text = (directory / ".cairn" / "events.jsonl").read_text(
            encoding="utf-8", errors="replace"
        )
    except OSError:
        return 0
    count = 0
    for line in text.split("\\n"):
        if not line.strip():
            continue
        try:
            if json.loads(line).get("op") == "save":
                count += 1
        except ValueError:
            pass
    return count


def main() -> None:
    state = json.load(sys.stdin)
    if state.get("stop_hook_active"):
        return
    root = Path(state.get("cwd") or Path.cwd())
    state_dir = root / ".cairn-nudge"
    session = str(state.get("session_id") or "unknown")
    marker = state_dir / f"{session}.seen"
    if marker.exists():
        return
    baseline = 0
    try:
        baseline = int((state_dir / "baseline").read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        pass
    if _saves(root) > baseline:
        return
    state_dir.mkdir(parents=True, exist_ok=True)
    marker.write_text("", encoding="utf-8", newline="\\n")
    with (root / ".cairn-nudge.log").open("a", encoding="utf-8", newline="\\n") as handle:
        handle.write(session + "\\n")
    print(json.dumps({"decision": "block", "reason": NUDGE}))


if __name__ == "__main__":
    main()
'''.replace("@NUDGE@", CC_NUDGE)


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


def _install_cc_hook(directory: Path) -> None:
    """El hook Stop de Claude Code: settings.json del repo + el script, y la línea base
    de saves en el momento de instalar. `setup claude-code` solo lo instala si la ronda
    pasa, igual que S28 hizo con OpenCode."""
    hooks_dir = directory / ".claude" / "hooks"
    hooks_dir.mkdir(parents=True)
    script = hooks_dir / "cairn_stop.py"
    script.write_text(CC_HOOK, encoding="utf-8", newline="\n")
    settings = {
        "hooks": {
            "Stop": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            # Git Bash (el shell de los hooks en Windows) no lleva la
                            # barra invertida bien dentro de comillas en todas las rutas.
                            "command": f'"{sys.executable}" "{script.as_posix()}"',
                        }
                    ]
                }
            ]
        }
    }
    (directory / ".claude" / "settings.json").write_text(
        json.dumps(settings, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    state_dir = directory / ".cairn-nudge"
    state_dir.mkdir(parents=True)
    (state_dir / "baseline").write_text(
        str(len(_save_ids(directory / ".cairn" / "events.jsonl"))),
        encoding="utf-8",
        newline="\n",
    )


def _prepare(directory: Path, arm: str, harness: str = "opencode") -> None:
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
    if arm == "stop":
        if harness == "claude-code":
            _install_cc_hook(directory)
        else:
            # La ruta real del usuario (S28): el banco mide el hook que instala `setup`,
            # no una copia del árbol de assets.
            install_hook("opencode", directory)


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


def _nudges(directory: Path) -> int:
    """Líneas del log del hook: una por sesión avisada (criterio 5 del protocolo)."""
    log = directory / ".cairn-nudge.log"
    if not log.exists():
        return 0
    return sum(
        1 for line in log.read_text(encoding="utf-8").splitlines() if line.strip()
    )


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


def _run_cc(directory: Path, prompt: str, timeout: int = 900) -> dict:
    """Una sesión headless de Claude Code. El contador de tokens es el `usage`
    acumulado del resultado (input + output + cache), el mismo metro en los dos brazos;
    `tools` aquí son turnos agénticos (`num_turns`), no llamadas a herramientas. Sin
    `--dangerously-skip-permissions`: la allowlist da al agente justo lo que pide la
    tarea (editar, correr los tests y guardar con cairn), y lo demás se deniega."""
    proc = subprocess.run(
        [
            "claude",
            "-p",
            prompt,
            "--output-format",
            "json",
            "--allowedTools",
            "Edit,Write,Bash(python -m pytest:*),Bash(pytest:*),Bash(cairn:*)",
        ],
        cwd=directory,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    try:
        result = json.loads(proc.stdout)
    except ValueError:
        result = {}
    usage = result.get("usage") or {}
    return {
        "answer": str(result.get("result") or "").strip(),
        "tokens": sum(
            usage.get(key) or 0
            for key in (
                "input_tokens",
                "output_tokens",
                "cache_creation_input_tokens",
                "cache_read_input_tokens",
            )
        ),
        "tools": int(result.get("num_turns") or 0),
        "exit": proc.returncode,
    }


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
    parser.add_argument(
        "--harness",
        choices=("opencode", "claude-code"),
        default="opencode",
        help="el CLI del agente que corre la sesión",
    )
    parser.add_argument("--json", action="store_true")
    ns = parser.parse_args(argv)
    arms = [arm.strip() for arm in ns.arms.split(",") if arm.strip()]
    runner = _run_cc if ns.harness == "claude-code" else _run
    timeout = 900 if ns.harness == "claude-code" else 420

    tmp = Path(tempfile.mkdtemp(prefix="cairn-abw-"))
    rows = []
    try:
        for rep in range(ns.reps):
            for arm in arms:
                project = tmp / f"{arm}-{rep}"
                _prepare(project, arm, harness=ns.harness)
                events = project / ".cairn" / "events.jsonl"
                before = _save_ids(events)
                result = runner(project, TASK, timeout=timeout)
                gotchas = _gotcha_saves(events, before)
                rows.append(
                    {
                        "arm": arm,
                        "rep": rep,
                        "exit": result["exit"],
                        "saved": bool(gotchas),
                        "saved_ids": [event["id"] for event in gotchas],
                        "nudges": _nudges(project),
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
        nudges = sum(row["nudges"] for row in subset) / max(1, len(subset))
        print(
            f"{arm:>11}: guardado {wins}/{len(subset)} "
            f"({wins / max(1, len(subset)):.0%}, IC95 {low:.2f}-{high:.2f}) · "
            f"tokens {tokens:,.0f} · llamadas {tools:.1f} · avisos {nudges:.1f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
