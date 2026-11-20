"""CLI de cairn-mem (M1)."""

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

from cairn_mem import __version__
from cairn_mem.anchor import is_stale, resolve_anchor
from cairn_mem.i18n import t
from cairn_mem.paths import data_dir, personal_dir
from cairn_mem.sessions import Sessions
from cairn_mem.setup import HARNESSES, setup
from cairn_mem.store import KINDS, Store, search_scopes

GITIGNORE = (
    "cairn.db",
    "cairn.db-*",
    "MEMORY.md",
    ".MEMORY.md.*",
    "sessions.jsonl",
    "*.lock",
)


def _root(ns) -> Path:
    return personal_dir() if getattr(ns, "personal", False) else data_dir()


def _store(ns) -> Store:
    return Store(str(_root(ns)))


def _existing_store(ns) -> Store:
    """Leer o regenerar no crea el scope personal."""
    root = personal_dir() if ns.personal else data_dir()
    if not root.exists():
        raise FileNotFoundError(
            t(
                "no personal scope yet; create one with 'cairn save --personal'",
                "no existe el scope personal; crea una memoria con 'cairn save --personal'",
            )
        )
    return Store(str(root))


def _scopes() -> list[Store]:
    """Proyecto primero y luego el scope personal, como `get` y `archive`."""
    stores = []
    try:
        stores.append(Store(str(data_dir())))
    except FileNotFoundError:
        pass
    if personal_dir().exists():
        stores.append(Store(str(personal_dir())))
    if not stores:
        raise FileNotFoundError(
            t(
                "no .cairn/ found in this tree; run 'cairn init'",
                "no se encontró .cairn/ en este árbol; ejecuta 'cairn init'",
            )
        )
    return stores


def _date(ts) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(int(ts) / 1e9))


def _print_json(value) -> None:
    print(json.dumps(value, ensure_ascii=False))


def _write_gitignore(root: Path, share: bool) -> None:
    """Conserva las líneas que no gestiona cairn; solo actualiza las suyas."""
    path = root / ".gitignore"
    managed = {"events.jsonl", *GITIGNORE}
    kept = []
    if path.exists():
        kept = [
            line
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and line not in managed
        ]
    lines = [*kept, *GITIGNORE]
    if not share:
        lines.append("events.jsonl")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _cmd_init(ns) -> int:
    env = os.environ.get("CAIRN_DIR")
    local = Path.cwd() / ".cairn"
    if env:
        root = Path(env)
    else:
        try:
            existing = data_dir()
        except FileNotFoundError:
            existing = None
        if existing is not None and existing.resolve() != local.resolve():
            raise ValueError(
                t(
                    f"a store already exists at {existing}; use that root or set CAIRN_DIR",
                    f"ya existe un store en {existing}; usa esa raíz o define CAIRN_DIR",
                )
            )
        root = existing or local
    personal = personal_dir().resolve()
    if root.resolve() == personal or root.resolve().is_relative_to(personal):
        raise ValueError(
            t(
                "that folder is inside the cairn personal scope; "
                "set CAIRN_HOME or change directory",
                "esa carpeta está dentro del scope personal de cairn; "
                "define CAIRN_HOME o cambia de directorio",
            )
        )
    root.mkdir(parents=True, exist_ok=True)
    (root / "events.jsonl").touch()
    _write_gitignore(root, ns.share)
    Store(str(root))
    print(t(f"cairn initialized at {root}", f"cairn inicializado en {root}"))
    return 0


def _cmd_save(ns) -> int:
    anchor_path = anchor_hash = None
    root = _root(ns)
    if ns.anchor:
        anchor_path, anchor_hash = resolve_anchor(ns.anchor, root.parent)
    store = _store(ns)
    mid = store.save(
        kind=ns.kind,
        title=ns.title,
        body=ns.body,
        why=ns.why,
        topic_key=ns.topic,
        anchor_path=anchor_path,
        anchor_hash=anchor_hash,
        id=ns.id,
        source=ns.source,
        keywords=ns.keywords,
    )
    similar = [row for row in store.similar(ns.title, ns.body) if row["id"] != mid]
    if ns.json:
        payload: dict[str, object] = {"id": mid}
        if similar:
            payload["similar"] = similar
        _print_json(payload)
    else:
        print(mid)
        for row in similar:
            print(
                f"similar: {row['id']}  {row['kind']}  {row['title']}  "
                f"({row['overlap']:.0%})",
                file=sys.stderr,
            )
    return 0


def _cmd_search(ns) -> int:
    personal = None
    if not ns.project and personal_dir().exists():
        personal = Store(str(personal_dir()))
    project = None
    if not ns.personal:
        try:
            project = Store(str(data_dir()))
        except FileNotFoundError:
            if ns.project or personal is None:
                raise  # sin proyecto ni scope personal no hay nada que buscar
    results = search_scopes(
        project,
        personal,
        ns.query,
        limit=ns.limit,
        kind=ns.kind,
        topic=ns.topic,
        stale=ns.stale,
    )
    if ns.json:
        _print_json(results)
    elif not results:
        print(t("no results", "sin resultados"))
    else:
        for r in results:
            snippet = " ".join(r["snippet"].split())
            topic = f"  [{r['topic_key']}]" if r.get("topic_key") else ""
            scope = "  [personal]" if r["scope"] == "personal" else ""
            source = f"  ({r['source']})" if r.get("source") else ""
            stale = t("  ⚠ review", "  ⚠ revisar") if r["stale"] else ""
            partial = t("  (partial)", "  (parcial)") if r.get("partial") else ""
            print(
                f"{r['id']}  {r['kind']}{topic}{scope}  {r['title']} — {snippet}"
                f"{source}{stale}{partial}"
            )
    return 0


def _cmd_get(ns) -> int:
    memory = None
    for store in _scopes():
        memory = store.get(ns.id)
        if memory is not None:
            break
    if memory is None:
        raise ValueError(_missing(ns.id))
    if ns.json:
        _print_json(memory)
    else:
        for key, value in memory.items():
            if value is not None:
                print(f"{key}: {value}")
    return 0


def _missing(memory_id: str) -> str:
    return t(f"memory {memory_id} does not exist", f"no existe la memoria {memory_id}")


def _cmd_archive(ns) -> int:
    for store in _scopes():
        if store.get(ns.id) is not None:
            store.archive(ns.id)
            print(t(f"archived {ns.id}", f"archivada {ns.id}"))
            return 0
    raise ValueError(_missing(ns.id))


def _cmd_pin(ns) -> int:
    for store in _scopes():
        if store.get(ns.id) is not None:
            store.pin(ns.id)
            print(t(f"pinned {ns.id}", f"pineada {ns.id}"))
            return 0
    raise ValueError(_missing(ns.id))


def _cmd_unpin(ns) -> int:
    for store in _scopes():
        if store.get(ns.id) is not None:
            store.unpin(ns.id)
            print(t(f"unpinned {ns.id}", f"despineada {ns.id}"))
            return 0
    raise ValueError(_missing(ns.id))


def _cmd_purge(ns) -> int:
    for store in _scopes():
        if store.get(ns.id) is not None:
            removed = store.purge(ns.id)
            print(
                t(
                    f"purged {removed} lines of {ns.id} (backup: events.jsonl.bak)",
                    f"purgadas {removed} líneas de {ns.id} (copia: events.jsonl.bak)",
                )
            )
            print(
                t(
                    "cairn: if it was a secret, rotate the credential now; with --share "
                    "the Git history may keep it",
                    "cairn: si era un secreto, rota la credencial ahora; con --share "
                    "el historial de Git puede conservarla",
                ),
                file=sys.stderr,
            )
            return 0
    raise ValueError(_missing(ns.id))


def _cmd_topics(ns) -> int:
    rows = []
    for store in _scopes():
        scope = "personal" if store.root == personal_dir() else "project"
        rows += [{**row, "scope": scope} for row in store.topics()]
    if ns.json:
        _print_json(rows)
    elif not rows:
        print(t("no topics", "sin topics"))
    else:
        for row in rows:
            tag = "  [personal]" if row["scope"] == "personal" else ""
            print(f"{row['topic']}  ({row['count']}){tag}")
    return 0


def _cmd_history(ns) -> int:
    rows = []
    for store in _scopes():
        scope = "personal" if store.root == personal_dir() else "project"
        rows += [{**row, "scope": scope} for row in store.history(ns.topic)]
    rows.sort(key=lambda row: (row["ts"], row["id"]))
    if ns.json:
        _print_json(rows)
    elif not rows:
        print(t("no history for that topic", "sin historial para ese topic"))
    else:
        for row in rows:
            tag = "  [personal]" if row["scope"] == "personal" else ""
            print(
                f"{row['id']}  {_date(row['ts'])}  {row['kind']}  "
                f"{row['status']}  {row['title']}{tag}"
            )
    return 0


def _cmd_rebuild(ns) -> int:
    store = _existing_store(ns)
    store.rebuild()
    print(
        t(
            f"rebuilt: {len(store.dump())} memories",
            f"reconstruida: {len(store.dump())} memorias",
        )
    )
    return 0


def _cmd_render(ns) -> int:
    print(_existing_store(ns).write_l0(), end="")
    return 0


def _cmd_check(ns) -> int:
    store = _existing_store(ns)
    project_root = store.root.parent
    stale = [
        row
        for row in store.dump()
        if row["status"] == "active"
        and is_stale(
            row["anchor_path"], row["anchor_hash"], project_root, max_bytes=float("inf")
        )
    ]
    if ns.json:
        _print_json(
            [
                {
                    "id": row["id"],
                    "kind": row["kind"],
                    "title": row["title"],
                    "anchor_path": row["anchor_path"],
                }
                for row in stale
            ]
        )
    elif not stale:
        print(t("no stale memories", "sin memorias stale"))
    else:
        for row in stale:
            print(f"{row['id']}  {row['kind']}  {row['title']}  ({row['anchor_path']})")
    return 0


def _ignore_sessions(root) -> None:
    """Sesiones locales: `init` las ignora, pero el scope personal no pasa por init."""
    path = Path(root) / ".gitignore"
    if not path.exists():
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    if "sessions.jsonl" not in lines:
        path.write_text(
            "\n".join([*lines, "sessions.jsonl"]) + "\n", encoding="utf-8", newline="\n"
        )


def _cmd_session_save(ns) -> int:
    root = personal_dir() if ns.personal else data_dir()
    _ignore_sessions(root)
    sid = Sessions(str(root)).save(ns.summary)
    _print_json({"id": sid}) if ns.json else print(sid)
    return 0


def _cmd_session_list(ns) -> int:
    root = personal_dir() if ns.personal else data_dir()
    records = Sessions(str(root)).all(limit=ns.limit)
    if ns.json:
        _print_json(records)
    elif not records:
        print(t("no sessions", "sin sesiones"))
    else:
        for record in records:
            first = " ".join(record["summary"].split())[:80]
            print(f"{record['id']}  {_date(record.get('ts', 0))}  {first}")
    return 0


def _cmd_session_get(ns) -> int:
    root = personal_dir() if ns.personal else data_dir()
    record = Sessions(str(root)).get(ns.id)
    if record is None:
        raise ValueError(
            t(f"session {ns.id} does not exist", f"no existe la sesión {ns.id}")
        )
    if ns.json:
        _print_json(record)
    else:
        print(record["summary"])
    return 0


def _cmd_import(ns) -> int:
    from cairn_mem.legacy import import_legacy

    report = import_legacy(ns.db, dry_run=ns.dry_run)
    if ns.json:
        _print_json(report)
        return 0
    prefix = (
        t("would import", "se importarían")
        if ns.dry_run
        else t("imported", "importadas")
    )
    print(
        t(
            f"{prefix} {report['memories']} memories and {report['sessions']} sessions "
            f"({report['skipped']} skipped, {report['rejected']} rejected, "
            f"{report['foreign']} from other repos)",
            f"{prefix} {report['memories']} memorias y {report['sessions']} sesiones "
            f"({report['skipped']} omitidas, {report['rejected']} rechazadas, "
            f"{report['foreign']} de otros repos)",
        )
    )
    return 0


def _cmd_mcp(ns) -> int:
    from cairn_mem.mcp import serve

    return serve(read_only=ns.read_only)


def _cmd_setup(ns) -> int:
    for line in setup(ns.harness, Path(ns.dir) if ns.dir else Path.cwd()):
        print(line)
    return 0


def _cmd_export(ns) -> int:
    from cairn_mem.export import render_markdown

    root = personal_dir() if ns.personal else data_dir()
    if not root.exists():
        raise FileNotFoundError(
            t(f"no {root}; run 'cairn init'", f"no existe {root}; ejecuta 'cairn init'")
        )
    store = Store(str(root))
    sessions = Sessions(str(root)) if ns.sessions else None
    text = render_markdown(store, sessions, ns.sessions)
    if ns.out:
        Path(ns.out).write_text(text, encoding="utf-8", newline="\n")
        print(ns.out)
    else:
        print(text, end="")
    return 0


def _cmd_doctor(ns) -> int:
    from cairn_mem.doctor import run

    root = None
    if ns.personal:
        # Igual que `search --personal`: leer no crea el scope personal.
        root = personal_dir() if personal_dir().exists() else None
    else:
        try:
            candidate = data_dir()
        except FileNotFoundError:
            candidate = None
        # `CAIRN_DIR` no comprueba existencia: diagnosticar no puede crear el store.
        root = candidate if candidate is not None and candidate.exists() else None
    checks = run(root)
    if ns.json:
        _print_json(checks)
    else:
        for item in checks:
            print(f"{item['status']:<4}  {item['check']:<10}  {item['detail']}")
    return 1 if any(item["status"] == "fail" for item in checks) else 0


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cairn",
        description=t(
            "Persistent memory for agents", "Memoria persistente para agentes"
        ),
    )
    sub = p.add_subparsers(dest="command", required=True)

    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    init = sub.add_parser(
        "init",
        help=t(
            "creates .cairn/ (local-only by default)",
            "crea .cairn/ (local-only por defecto)",
        ),
    )
    init.add_argument(
        "--share",
        action="store_true",
        help=t("versions events.jsonl", "versiona events.jsonl"),
    )
    init.set_defaults(handler=_cmd_init)

    save = sub.add_parser("save", help=t("saves a memory", "guarda una memoria"))
    save.add_argument("--kind", required=True, choices=KINDS)
    save.add_argument("--title", required=True)
    save.add_argument("--body", required=True)
    save.add_argument("--why")
    save.add_argument("--topic", dest="topic")
    save.add_argument(
        "--source",
        help=t(
            "provenance: agent, model or session",
            "procedencia: agente, modelo o sesión",
        ),
    )
    save.add_argument(
        "--keywords",
        help=t(
            "synonyms that should find this memory",
            "sinónimos con los que debe encontrarse esta memoria",
        ),
    )
    save.add_argument("--anchor")
    save.add_argument("--id")
    save.add_argument(
        "--personal", action="store_true", help=t("personal scope", "scope personal")
    )
    save.add_argument("--json", action="store_true")
    save.set_defaults(handler=_cmd_save)

    search = sub.add_parser(
        "search", help=t("searches active memories", "busca memorias activas")
    )
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=5)
    search.add_argument("--kind", choices=KINDS)
    search.add_argument("--topic", help=t("exact topic_key", "topic_key exacto"))
    search.add_argument(
        "--stale",
        action="store_true",
        help=t(
            "only memories whose anchor changed",
            "solo memorias con el ancla cambiada",
        ),
    )
    scope = search.add_mutually_exclusive_group()
    scope.add_argument(
        "--project", action="store_true", help=t("project only", "solo el proyecto")
    )
    scope.add_argument(
        "--personal", action="store_true", help=t("personal scope", "scope personal")
    )
    search.add_argument("--json", action="store_true")
    search.set_defaults(handler=_cmd_search)

    get = sub.add_parser(
        "get", help=t("shows one full memory", "muestra una memoria completa")
    )
    get.add_argument("id")
    get.add_argument("--json", action="store_true")
    get.set_defaults(handler=_cmd_get)

    archive = sub.add_parser(
        "archive", help=t("archives a memory", "archiva una memoria")
    )
    archive.add_argument("id")
    archive.set_defaults(handler=_cmd_archive)

    pin = sub.add_parser(
        "pin",
        help=t(
            "pins a memory at the top of the L0 (human)",
            "fija una memoria al principio del L0 (humano)",
        ),
    )
    pin.add_argument("id")
    pin.set_defaults(handler=_cmd_pin)

    unpin = sub.add_parser(
        "unpin", help=t("removes a pin", "quita el pin de una memoria")
    )
    unpin.add_argument("id")
    unpin.set_defaults(handler=_cmd_unpin)

    purge = sub.add_parser(
        "purge",
        help=t(
            "deletes a memory from the JSONL (leaked secret)",
            "borra una memoria del JSONL (secreto filtrado)",
        ),
    )
    purge.add_argument("id")
    purge.set_defaults(handler=_cmd_purge)

    topics = sub.add_parser(
        "topics", help=t("lists active topic_keys", "lista los topic_key activos")
    )
    topics.add_argument("--json", action="store_true")
    topics.set_defaults(handler=_cmd_topics)

    history = sub.add_parser(
        "history",
        help=t(
            "shows every version of a topic_key",
            "muestra todas las versiones de un topic_key",
        ),
    )
    history.add_argument("topic", help=t("exact topic_key", "topic_key exacto"))
    history.add_argument("--json", action="store_true")
    history.set_defaults(handler=_cmd_history)

    rebuild = sub.add_parser(
        "rebuild",
        help=t(
            "rebuilds the DB from events.jsonl",
            "reconstruye la DB desde events.jsonl",
        ),
    )
    rebuild.add_argument(
        "--personal", action="store_true", help=t("personal scope", "scope personal")
    )
    rebuild.set_defaults(handler=_cmd_rebuild)

    render = sub.add_parser(
        "render",
        help=t(
            "regenerates and prints MEMORY.md (L0)",
            "regenera y muestra MEMORY.md (L0)",
        ),
    )
    render.add_argument(
        "--personal", action="store_true", help=t("personal scope", "scope personal")
    )
    render.set_defaults(handler=_cmd_render)

    check = sub.add_parser(
        "check",
        help=t("lists memories with a stale anchor", "lista memorias con ancla stale"),
    )
    check.add_argument(
        "--personal", action="store_true", help=t("personal scope", "scope personal")
    )
    check.add_argument("--json", action="store_true")
    check.set_defaults(handler=_cmd_check)

    session = sub.add_parser("session", help=t("session recaps", "resúmenes de sesión"))
    session_sub = session.add_subparsers(dest="session_command", required=True)
    session_save = session_sub.add_parser(
        "save", help=t("saves a recap", "guarda un resumen")
    )
    session_save.add_argument("--summary", required=True)
    session_save.add_argument(
        "--personal", action="store_true", help=t("personal scope", "scope personal")
    )
    session_save.add_argument("--json", action="store_true")
    session_save.set_defaults(handler=_cmd_session_save)
    session_list = session_sub.add_parser(
        "list", help=t("lists recent sessions", "lista sesiones recientes")
    )
    session_list.add_argument("--limit", type=int, default=20)
    session_list.add_argument(
        "--personal", action="store_true", help=t("personal scope", "scope personal")
    )
    session_list.add_argument("--json", action="store_true")
    session_list.set_defaults(handler=_cmd_session_list)
    session_get = session_sub.add_parser(
        "get", help=t("shows a full recap", "muestra un resumen completo")
    )
    session_get.add_argument("id")
    session_get.add_argument(
        "--personal", action="store_true", help=t("personal scope", "scope personal")
    )
    session_get.add_argument("--json", action="store_true")
    session_get.set_defaults(handler=_cmd_session_get)

    importer = sub.add_parser(
        "import",
        help=t(
            "imports memory from another tool", "importa memoria de otra herramienta"
        ),
    )
    importer.add_argument("source", choices=["legacy"])
    importer.add_argument(
        "--db",
        required=True,
        help=t("path to the source SQLite database", "ruta a la base SQLite de origen"),
    )
    importer.add_argument("--dry-run", action="store_true")
    importer.add_argument("--json", action="store_true")
    importer.set_defaults(handler=_cmd_import)

    mcp = sub.add_parser(
        "mcp",
        help=t("serves MCP over stdio (JSON-RPC)", "sirve MCP por stdio (JSON-RPC)"),
    )
    mcp.add_argument(
        "--read-only",
        action="store_true",
        help=t(
            "exposes only the read tools; rejects save/save_session/archive",
            "solo expone las tools de lectura; rechaza save/save_session/archive",
        ),
    )
    mcp.set_defaults(handler=_cmd_mcp)

    doctor = sub.add_parser(
        "doctor",
        help=t(
            "diagnoses the store and the install",
            "diagnostica el store y la instalación",
        ),
    )
    doctor.add_argument(
        "--personal", action="store_true", help=t("personal scope", "scope personal")
    )
    doctor.add_argument("--json", action="store_true")
    doctor.set_defaults(handler=_cmd_doctor)

    setup_cmd = sub.add_parser(
        "setup",
        help=t(
            "configures MCP and rules for a harness (claude-code, opencode)",
            "configura MCP y reglas para un harness (claude-code, opencode)",
        ),
    )
    setup_cmd.add_argument("harness", choices=sorted(HARNESSES))
    setup_cmd.add_argument(
        "--dir",
        help=t("repo root (the cwd by default)", "raíz del repo (por defecto el cwd)"),
    )
    setup_cmd.set_defaults(handler=_cmd_setup)

    export = sub.add_parser(
        "export",
        help=t(
            "dumps active memory to Markdown",
            "vuelca la memoria activa a Markdown",
        ),
    )
    export.add_argument(
        "--personal", action="store_true", help=t("personal scope", "scope personal")
    )
    export.add_argument(
        "--sessions",
        type=int,
        default=0,
        help=t("includes the last N sessions", "incluye las últimas N sesiones"),
    )
    export.add_argument(
        "--out",
        help=t(
            "output file (stdout by default)", "fichero de salida (por defecto stdout)"
        ),
    )
    export.set_defaults(handler=_cmd_export)
    return p


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ns = _parser().parse_args(argv)
    try:
        return ns.handler(ns)
    except (ValueError, OSError) as error:
        print(f"cairn: {error}", file=sys.stderr)
        return 1
    except sqlite3.DatabaseError as error:
        if any(
            word in str(error).lower()
            for word in ("not a database", "corrupt", "malformed")
        ):
            print(
                t(
                    "cairn: corrupt database; delete .cairn/cairn.db and run "
                    "'cairn rebuild'",
                    "cairn: base de datos corrupta; borra .cairn/cairn.db y ejecuta "
                    "'cairn rebuild'",
                ),
                file=sys.stderr,
            )
        else:
            print(
                t(
                    f"cairn: database error: {error}",
                    f"cairn: error de base de datos: {error}",
                ),
                file=sys.stderr,
            )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
