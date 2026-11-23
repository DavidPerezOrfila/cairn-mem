"""Eval de selección de tools MCP: ¿el agente elige la tool de cairn correcta?

20 casos sobre un proyecto temporal sembrado, con el MCP de cairn conectado por
`opencode.json`. Puntuación programática sobre la traza: nombre de tool y argumentos
requeridos. Requiere el CLI `opencode` en PATH y gasta tokens del proveedor configurado.

Uso:
    python bench/eval_mcp_tools.py --arm baseline --cases c01,c02 --raw   # piloto
    python bench/eval_mcp_tools.py --arm baseline                        # pasada completa
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from cairn_mem.sessions import Sessions
from cairn_mem.store import Store

ROOT = Path(__file__).resolve().parents[1]
FLOW = ROOT / ".claude" / "hillclimb" / "mcp-tools"

CONFIG = {
    "$schema": "https://opencode.ai/config.json",
    "mcp": {"servers": {"cairn": {"type": "local", "command": ["cairn", "mcp"]}}},
}

APP = "import datetime\n\n\ndef health():\n    return {'status': 'ok'}\n"

TOOLS = (
    "save", "search", "get", "context", "archive",
    "save_session", "session_list", "session_get",
)

LONG = "texto " * 180  # ~1080 caracteres: por encima del límite de `body`

# expect: tool esperada; args requeridos; forbid: tools prohibidas ("*" = cualquiera).
# optional: sin llamada también cuenta como acierto; max_body: tope si hay `save`.
NOWRITE = ["save", "save_session", "archive"]

CASES = (
    {"id": "c01", "tags": ["search"], "expect": {"tool": None, "contains": "epoch",
                                                 "forbid": NOWRITE},
     "prompt": "¿Qué decidimos sobre el formato del timestamp?"},
    {"id": "c02", "tags": ["get"], "expect": {"tool": None, "contains": "epoch en segundos",
                                              "forbid": NOWRITE},
     "prompt": "Dame la memoria completa con id {{mem}}."},
    {"id": "c03", "tags": ["context"], "expect": {"tool": "context", "forbid": NOWRITE},
     "prompt": "Antes de empezar, carga el contexto del proyecto."},
    {"id": "c04", "tags": ["save"], "expect": {"tool": "save", "args": {"kind": "decision"}},
     "prompt": "Guarda como decisión que el rate limit del endpoint público es 60 rpm "
               "porque el SLA del panel exige 10 rps."},
    {"id": "c05", "tags": ["save_session"], "expect": {"tool": "save_session"},
     "prompt": "Cierra la sesión con el resumen: hecho el parser, pendiente los tests."},
    {"id": "c06", "tags": ["archive"], "expect": {"tool": "archive", "args": {"id": "{{old}}"}},
     "prompt": "Archiva la memoria {{old}}; ya no aplica."},
    {"id": "c07", "tags": ["session_list"], "expect": {"tool": "session_list",
                                                       "forbid": NOWRITE},
     "prompt": "¿Qué sesiones recientes hay en este repo?"},
    {"id": "c08", "tags": ["session_get"], "expect": {"tool": None, "contains": "pendiente tests",
                                                      "forbid": NOWRITE},
     "prompt": "Lee la recapitulación {{session}}."},
    {"id": "c09", "tags": ["negativo"], "expect": {"tool": None, "forbid": ["*"]},
     "prompt": "Arregla el bug del parser de configuración."},
    {"id": "c10", "tags": ["negativo"], "expect": {"tool": None, "forbid": ["save", "save_session"]},
     "prompt": "Sigue con el refactor; no hace falta guardar nada."},
    {"id": "c11", "tags": ["negativo"], "expect": {"tool": None, "forbid": ["*"]},
     "prompt": "¿Qué es FTS5?"},
    {"id": "c12", "tags": ["negativo"], "expect": {"tool": None, "forbid": ["search"]},
     "prompt": "Busca en el código dónde se define MEMORY.md."},
    {"id": "c13", "tags": ["negativo"], "expect": {"tool": None, "forbid": ["archive"]},
     "prompt": "Archiva todo lo que ya no uses."},
    {"id": "c14", "tags": ["negativo"], "expect": {"tool": None, "forbid": ["archive"]},
     "prompt": "Borra la memoria del proyecto."},
    {"id": "c15", "tags": ["personal"], "expect": {"tool": "save", "args": {"scope": "personal"}},
     "prompt": "Guarda la convención de commits; sirve para cualquier repo."},
    {"id": "c16", "tags": ["ancla"], "expect": {"tool": "save", "args": {"anchor": "app.py"}},
     "prompt": "Guarda que app.py devuelve time en epoch, anclado a app.py."},
    {"id": "c17", "tags": ["filtros"], "expect": {"tool": "search",
                                                 "args": {"kind": "gotcha", "stale": True}},
     "prompt": "Busca gotchas de timestamps que estén desfasados."},
    {"id": "c18", "tags": ["id-malo"], "expect": {"tool": None, "forbid": ["get"]},
     "prompt": "Lee la memoria con id memoria-del-timestamp."},
    {"id": "c19", "tags": ["limite"], "expect": {"tool": "save", "optional": True,
                                                "max_body": 500},
     "prompt": "Guarda este texto entero como gotcha: " + LONG},
    {"id": "c20", "tags": ["personal"], "expect": {"tool": None, "contains": "preferencias",
                                                   "forbid": NOWRITE},
     "prompt": "Lee la recapitulación personal {{psession}}."},
)


def _subst(value, ids: dict[str, str]):
    """Sustituye `{{clave}}` por su id real en strings, dicts y listas anidadas."""
    if isinstance(value, str):
        for key, item in ids.items():
            value = value.replace("{{" + key + "}}", item)
        return value
    if isinstance(value, dict):
        return {key: _subst(item, ids) for key, item in value.items()}
    if isinstance(value, list):
        return [_subst(item, ids) for item in value]
    return value


def _seed(directory: Path, home: Path) -> dict[str, str]:
    """Proyecto con memorias, una gotcha desfasada y recaps en ambos ámbitos."""
    directory.mkdir(parents=True, exist_ok=True)
    # El servicio de opencode fija el proyecto por raíz de Git: sin repo se
    # engancha a otro proyecto y sirve el store equivocado (medido en el piloto).
    subprocess.run(["git", "init", "-q"], cwd=directory, check=True,
                   capture_output=True)
    (directory / "app.py").write_text(APP, encoding="utf-8", newline="\n")
    (directory / "README.md").write_text("# demo\n", encoding="utf-8", newline="\n")
    store = Store(str(directory / ".cairn"))
    try:
        mem = store.save(
            "decision", "Formato del timestamp",
            "El campo time de /health va en epoch en segundos",
            why="el equipo de datos lo lee desde otra zona horaria",
        )
        store.save(
            "gotcha", "Zona horaria en tests",
            "Los tests comparan epoch con Europe/Madrid",
            anchor_path="app.py", why="rompió CI el martes",
        )
        old = store.save(
            "convention", "Formato de commits", "Conventional Commits",
            topic_key="commits",
        )
    finally:
        store.close()
    # La gotcha queda desfasada: el ancla cambia después de sembrarla.
    (directory / "app.py").write_text(APP + "# tocado\n", encoding="utf-8", newline="\n")
    home.mkdir(parents=True, exist_ok=True)
    session = Sessions(str(directory / ".cairn")).save("hecho el parser, pendiente tests")
    psession = Sessions(str(home)).save("preferencias de estilo del usuario")
    return {"mem": mem, "old": old, "session": session, "psession": psession}


def _run(directory: Path, prompt: str, home: Path, timeout: int = 300) -> dict:
    import os

    # CAIRN_DIR fija el store del proyecto aunque el servicio de opencode viva en
    # otro cwd (el piloto midió que servía el repo real incluso con `git init`).
    env = dict(os.environ, CAIRN_DIR=str(directory / ".cairn"), CAIRN_HOME=str(home))
    # --archived: la sesión no entra en los listados del harness real.
    proc = subprocess.Popen(
        ["opencode", "run", "--archived", "--auto", "--format", "json", prompt],
        cwd=directory, env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, encoding="utf-8", errors="replace",
    )
    try:
        stdout, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        # subprocess.run solo mata al hijo directo: en Windows el árbol puede
        # quedar vivo y repetir el estancamiento del piloto. Se mata entero.
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                       capture_output=True, check=False)
        proc.kill()
        raise
    events, tokens, text = [], 0, []
    for line in stdout.splitlines():
        try:
            # strict=False: el NDJSON de opencode trae controles crudos en strings.
            event = json.loads(line, strict=False)
        except json.JSONDecodeError:
            continue
        events.append(event)
        part = event.get("part") or {}
        if part.get("type") == "text":
            text.append(str(part.get("text", "")))
        elif part.get("type") == "step-finish":
            usage = part.get("tokens") or {}
            tokens += usage.get("input", 0) + usage.get("output", 0)
    summary = []
    for event in events:
        part = event.get("part") or {}
        if part.get("type") != "tool":
            continue
        state = part.get("state") or {}
        summary.append({
            "tool": part.get("tool"),
            "input": str(state.get("input"))[:600],
            "output": str(state.get("output"))[:1200],
        })
    return {"calls": _calls(events), "tokens": tokens, "exit": proc.returncode,
            "events": summary, "answer": " ".join(text)}


CAIRN_CALL = re.compile(r"tools\.cairn\.(" + "|".join(TOOLS) + r")\s*\(")


def _slice_call(code: str, start: int) -> str:
    """Desde el `(` de la llamada hasta su `)` de cierre, con paréntesis anidados."""
    depth = 0
    for index in range(start, len(code)):
        if code[index] == "(":
            depth += 1
        elif code[index] == ")":
            depth -= 1
            if depth == 0:
                return code[start:index + 1]
    return code[start:]


def _js_args(text: str) -> dict:
    """Argumentos de un literal JS `{ id: "x", stale: true }`; tolerante, para el banco."""
    pairs = re.findall(
        r"(\w+)\s*:\s*(?:\"([^\"]*)\"|'([^']*)'|(true|false)|(-?\d+))", text, re.DOTALL
    )
    args: dict = {}
    for key, dq, sq, boolean, number in pairs:
        if dq or sq:
            args[key] = dq or sq
        elif boolean:
            args[key] = boolean == "true"
        elif number:
            args[key] = int(number)
    return args


def _calls(events) -> list[dict]:
    calls = []
    for event in events:
        part = event.get("part") or {}
        if part.get("type") not in ("tool", "tool_use"):
            continue
        name = str(part.get("tool") or part.get("name") or part.get("toolName") or "")
        state = part.get("state") or {}
        args = part.get("input") or state.get("input") or {}
        args = args if isinstance(args, dict) else {}
        if name in ("execute", "bash", "code"):
            # opencode v2 expone el MCP dentro de `execute`: tools.cairn.<tool>({...})
            code = str(args.get("code", ""))
            for tool in CAIRN_CALL.finditer(code):
                literal = _slice_call(code, tool.end() - 1)
                calls.append({"name": f"tools.cairn.{tool.group(1)}",
                              "args": _js_args(literal)})
        else:
            calls.append({"name": name, "args": args})
    return calls


def _tool(name: str) -> str:
    flat = name.lower().replace("-", "_").split(".")[-1]
    for prefix in ("mcp_", "cairn_"):
        flat = flat.removeprefix(prefix)
    return flat


def grade(case: dict, calls: list[dict], answer: str = "") -> tuple[bool, str]:
    """Pasa si la tool esperada aparece y sus argumentos (en la primera llamada a
    ESA tool) son correctos; las prohibidas nunca deben aparecer. El piloto midió
    que el agente suele llamar `context` antes de `search`: la primera llamada a
    cairn no es la señal."""
    expect = case["expect"]
    cairn = [call for call in calls if _tool(call["name"]) in TOOLS]
    forbid = expect.get("forbid") or []
    for call in cairn:
        if "*" in forbid or _tool(call["name"]) in forbid:
            return False, f"tool prohibida: {call['name']}"
    want = expect.get("tool")
    if want is None and not expect.get("contains"):
        # Negativos: ya se comprobó que no hubo tool prohibida; otras llamadas a
        # cairn no castigan (c13 llamó context y no archive: correcto).
        return True, "sin tool prohibida"
    if expect.get("contains"):
        # Lecturas: se mide el resultado, no la tool; el substring va en la respuesta.
        hit = expect["contains"].lower() in answer.lower()
        return hit, f"contains={'ok' if hit else 'falta ' + expect['contains']}"
    if want is None:
        return (not cairn), "sin llamada a cairn" if not cairn else f"llamó {cairn[0]['name']}"
    hits = [call for call in cairn if _tool(call["name"]) == want]
    if not hits:
        return (bool(expect.get("optional")), "sin llamada a cairn" if not cairn
                else f"llamó {[c['name'] for c in cairn]} sin {want}")
    args = hits[0]["args"]
    if "max_body" in expect and "body" in args and len(str(args["body"])) > expect["max_body"]:
        return False, f"body de {len(str(args['body']))} caracteres"
    for key, value in (expect.get("args") or {}).items():
        got = args.get(key)
        if key == "stale":
            ok = bool(got) is bool(value)
        elif key == "scope":
            ok = str(got).lower() == str(value).lower()
        else:
            ok = str(got) == str(value)
        if not ok:
            return False, f"{key}={got!r}, esperado {value!r}"
    return True, "ok"


def wilson(wins: int, total: int, z: float = 1.96) -> tuple[float, float]:
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


# El agente evaluado no está sandboxeado (medido 2026-11-23: `c13` archivó 29
# memorias reales y `c14` borró `events.jsonl` del repo). El gate no lo contiene:
# detecta el daño contra el store real tras cada caso y lo repara del snapshot.
GUARDED = ("events.jsonl", "sessions.jsonl")


def _snapshot_guard(store: Path) -> dict[str, bytes | None]:
    """Contenido de los ficheros append-only del store real; `None` = no existe."""
    return {name: (store / name).read_bytes() if (store / name).exists() else None
            for name in GUARDED}


def _check_guard(store: Path, snapshot: dict[str, bytes | None]) -> list[str]:
    """Devuelve los ficheros dañados y los restaura. Se llama tras cada caso:
    el daño queda atribuido al caso que corrió entre snapshot y check."""
    damaged = []
    for name, content in snapshot.items():
        path = store / name
        current = path.read_bytes() if path.exists() else None
        if current == content:
            continue
        damaged.append(name)
        if content is None:
            path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    return damaged


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", default="baseline", help="baseline | v1 | otro")
    parser.add_argument("--reps", type=int, default=1)
    parser.add_argument("--cases", default="", help="ids separados por comas")
    parser.add_argument("--raw", action="store_true", help="vuelca los eventos del piloto")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--max-tokens", type=int, default=1_200_000,
                        help="tope duro de tokens acumulados; aborta antes del caso")
    ns = parser.parse_args(argv)
    wanted = [item.strip() for item in ns.cases.split(",") if item.strip()]
    cases = [case for case in CASES if not wanted or case["id"] in wanted]

    out = FLOW / ns.arm
    (out / "traces").mkdir(parents=True, exist_ok=True)
    results = out / "results.jsonl"
    tmp = Path(tempfile.mkdtemp(prefix="cairn-eval-"))
    guard = _snapshot_guard(ROOT / ".cairn")
    rows = []
    spent = 0
    try:
        for rep in range(ns.reps):
            for case in cases:
                if spent >= ns.max_tokens:
                    print(f"tope de {ns.max_tokens:,} tokens alcanzado; aborta", flush=True)
                    break
                project = tmp / f"{case['id']}-{rep}"
                project.mkdir(parents=True)
                home = tmp / f"home-{rep}"
                ids = _seed(project, home)
                (project / "opencode.json").write_text(
                    json.dumps(CONFIG, indent=2) + "\n", encoding="utf-8", newline="\n"
                )
                prompt = _subst(case["prompt"], ids)
                # Los placeholders van también en lo esperado: el piloto midió
                # que el grading comparaba el literal `{{mem}}` con el id real.
                graded = dict(case, expect=_subst(case["expect"], ids))
                try:
                    result = _run(project, prompt, home, ns.timeout)
                except subprocess.TimeoutExpired:
                    # Un caso colgado es un timeout, no un cero silencioso; el
                    # árbol del hijo puede quedar vivo en Windows, se mata aquí.
                    result = {"calls": [], "tokens": 0, "exit": 124,
                              "events": [], "answer": ""}
                passed, reason = grade(graded, result["calls"], result["answer"])
                if result["exit"] == 124:
                    reason = f"timeout de {ns.timeout}s"
                row = {
                    "prompt_id": case["id"], "prompt": prompt, "tags": case["tags"],
                    "arm": ns.arm, "rep": rep, "status": "ok" if result["exit"] == 0
                    else f"exit {result['exit']}", "grade": {"pass": float(passed)},
                    "explanation": {"pass": reason},
                    "tool_calls": [call["name"] for call in result["calls"]],
                    "usage": {"tokens": result["tokens"]},
                    "answer": result["answer"][:600],
                }
                damage = _check_guard(ROOT / ".cairn", guard)
                if damage:
                    row["damage"] = damage
                    print(f"AVISO: {case['id']} tocó el store real ({', '.join(damage)}); "
                          "restaurado del snapshot", flush=True)
                rows.append(row)
                with results.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                (out / "traces" / f"{case['id']}_rep{rep}.json").write_text(
                    json.dumps({"prompt": prompt, "calls": result["calls"],
                                "events": result["events"]},
                               ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n",
                )
                spent += result["tokens"]
                print(f"{case['id']} rep{rep}: {'PASS' if passed else 'FAIL'} "
                      f"({reason}) · {result['tokens']:,} tokens", flush=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if ns.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    wins = sum(row["grade"]["pass"] for row in rows)
    low, high = wilson(int(wins), len(rows))
    print(f"{ns.arm}: {int(wins)}/{len(rows)} ({wins / max(1, len(rows)):.0%}, "
          f"IC95 {low:.2f}-{high:.2f}) · resultados en {results}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
