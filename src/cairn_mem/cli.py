"""CLI de cairn-mem (M1)."""

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

from cairn_mem.anchor import is_stale, resolve_anchor
from cairn_mem.paths import data_dir, personal_dir
from cairn_mem.sessions import Sessions
from cairn_mem.store import KINDS, Store

GITIGNORE = ("cairn.db", "cairn.db-*", "MEMORY.md", "sessions.jsonl")


def _store(ns) -> Store:
    root = personal_dir() if getattr(ns, "personal", False) else data_dir()
    return Store(str(root))


def _date(ts) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(int(ts) / 1e9))


def _print_json(value) -> None:
    print(json.dumps(value, ensure_ascii=False))


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
                f"ya existe un store en {existing}; usa esa raíz o define CAIRN_DIR"
            )
        root = existing or local
    personal = personal_dir().resolve()
    if root.resolve() == personal or root.resolve().is_relative_to(personal):
        raise ValueError(
            "esa carpeta está dentro del scope personal de cairn; "
            "define CAIRN_HOME o cambia de directorio"
        )
    root.mkdir(parents=True, exist_ok=True)
    (root / "events.jsonl").touch()
    lines = list(GITIGNORE)
    if not ns.share:
        lines.append("events.jsonl")
    (root / ".gitignore").write_text("\n".join(lines) + "\n", encoding="utf-8")
    Store(str(root))
    print(f"cairn inicializado en {root}")
    return 0


def _cmd_save(ns) -> int:
    anchor_path = anchor_hash = None
    if ns.anchor:
        root = personal_dir() if ns.personal else data_dir()
        anchor_path, anchor_hash = resolve_anchor(ns.anchor, root.parent)
    mid = _store(ns).save(
        kind=ns.kind,
        title=ns.title,
        body=ns.body,
        why=ns.why,
        topic_key=ns.topic,
        anchor_path=anchor_path,
        anchor_hash=anchor_hash,
        id=ns.id,
    )
    _print_json({"id": mid}) if ns.json else print(mid)
    return 0


def _cmd_search(ns) -> int:
    results = _store(ns).search(ns.query, limit=ns.limit)
    if ns.json:
        _print_json(results)
    elif not results:
        print("sin resultados")
    else:
        for r in results:
            snippet = " ".join(r["snippet"].split())
            stale = "  ⚠ revisar" if r["stale"] else ""
            print(f"{r['id']}  {r['kind']}  {r['title']} — {snippet}{stale}")
    return 0


def _cmd_get(ns) -> int:
    stores = []
    try:
        stores.append(Store(str(data_dir())))
    except FileNotFoundError:
        pass
    home = personal_dir()
    if home.exists():
        stores.append(Store(str(home)))
    memory = None
    for store in stores:
        memory = store.get(ns.id)
        if memory is not None:
            break
    if memory is None:
        if not stores:
            raise FileNotFoundError(
                "no se encontró .cairn/ en este árbol; ejecuta 'cairn init'"
            )
        raise ValueError(f"no existe la memoria {ns.id}")
    if ns.json:
        _print_json(memory)
    else:
        for key, value in memory.items():
            if value is not None:
                print(f"{key}: {value}")
    return 0


def _cmd_archive(ns) -> int:
    store = _store(ns)
    if store.get(ns.id) is None:
        raise ValueError(f"no existe la memoria {ns.id}")
    store.archive(ns.id)
    print(f"archivada {ns.id}")
    return 0


def _cmd_rebuild(ns) -> int:
    store = Store(str(data_dir()))
    store.rebuild()
    print(f"reconstruida: {len(store.dump())} memorias")
    return 0


def _cmd_render(ns) -> int:
    print(Store(str(data_dir())).write_l0(), end="")
    return 0


def _cmd_check(ns) -> int:
    project_root = data_dir().parent
    stale = [
        row
        for row in Store(str(data_dir())).dump()
        if row["status"] == "active"
        and is_stale(row["anchor_path"], row["anchor_hash"], project_root)
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
        print("sin memorias stale")
    else:
        for row in stale:
            print(f"{row['id']}  {row['kind']}  {row['title']}  ({row['anchor_path']})")
    return 0


def _ignore_sessions(root) -> None:
    """Sesiones locales: los inits antiguos no las ignoraban."""
    path = Path(root) / ".gitignore"
    if not path.exists():
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    if "sessions.jsonl" not in lines:
        path.write_text("\n".join([*lines, "sessions.jsonl"]) + "\n", encoding="utf-8")


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
        print("sin sesiones")
    else:
        for record in records:
            first = " ".join(record["summary"].split())[:80]
            print(f"{record['id']}  {_date(record.get('ts', 0))}  {first}")
    return 0


def _cmd_session_get(ns) -> int:
    root = personal_dir() if ns.personal else data_dir()
    record = Sessions(str(root)).get(ns.id)
    if record is None:
        raise ValueError(f"no existe la sesión {ns.id}")
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
    prefix = "se importarían" if ns.dry_run else "importadas"
    print(
        f"{prefix} {report['memories']} memorias y {report['sessions']} sesiones "
        f"({report['skipped']} omitidas, {report['rejected']} rechazadas, "
        f"{report['foreign']} de otros repos)"
    )
    return 0


def _cmd_mcp(ns) -> int:
    from cairn_mem.mcp import serve

    return serve()


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cairn", description="Memoria persistente para agentes"
    )
    sub = p.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="crea .cairn/ (local-only por defecto)")
    init.add_argument("--share", action="store_true", help="versiona events.jsonl")
    init.set_defaults(handler=_cmd_init)

    save = sub.add_parser("save", help="guarda una memoria")
    save.add_argument("--kind", required=True, choices=KINDS)
    save.add_argument("--title", required=True)
    save.add_argument("--body", required=True)
    save.add_argument("--why")
    save.add_argument("--topic", dest="topic")
    save.add_argument("--anchor")
    save.add_argument("--id")
    save.add_argument("--personal", action="store_true", help="scope personal")
    save.add_argument("--json", action="store_true")
    save.set_defaults(handler=_cmd_save)

    search = sub.add_parser("search", help="busca memorias activas")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=5)
    search.add_argument("--personal", action="store_true", help="scope personal")
    search.add_argument("--json", action="store_true")
    search.set_defaults(handler=_cmd_search)

    get = sub.add_parser("get", help="muestra una memoria completa")
    get.add_argument("id")
    get.add_argument("--json", action="store_true")
    get.set_defaults(handler=_cmd_get)

    archive = sub.add_parser("archive", help="archiva una memoria")
    archive.add_argument("id")
    archive.add_argument("--personal", action="store_true", help="scope personal")
    archive.set_defaults(handler=_cmd_archive)

    rebuild = sub.add_parser("rebuild", help="reconstruye la DB desde events.jsonl")
    rebuild.set_defaults(handler=_cmd_rebuild)

    render = sub.add_parser("render", help="regenera y muestra MEMORY.md (L0)")
    render.set_defaults(handler=_cmd_render)

    check = sub.add_parser("check", help="lista memorias con ancla stale")
    check.add_argument("--json", action="store_true")
    check.set_defaults(handler=_cmd_check)

    session = sub.add_parser("session", help="resúmenes de sesión")
    session_sub = session.add_subparsers(dest="session_command", required=True)
    session_save = session_sub.add_parser("save", help="guarda un resumen")
    session_save.add_argument("--summary", required=True)
    session_save.add_argument("--personal", action="store_true", help="scope personal")
    session_save.add_argument("--json", action="store_true")
    session_save.set_defaults(handler=_cmd_session_save)
    session_list = session_sub.add_parser("list", help="lista sesiones recientes")
    session_list.add_argument("--limit", type=int, default=20)
    session_list.add_argument("--personal", action="store_true", help="scope personal")
    session_list.add_argument("--json", action="store_true")
    session_list.set_defaults(handler=_cmd_session_list)
    session_get = session_sub.add_parser("get", help="muestra un resumen completo")
    session_get.add_argument("id")
    session_get.add_argument("--personal", action="store_true", help="scope personal")
    session_get.add_argument("--json", action="store_true")
    session_get.set_defaults(handler=_cmd_session_get)

    importer = sub.add_parser("import", help="importa memoria de otra herramienta")
    importer.add_argument("source", choices=["legacy"])
    importer.add_argument("--db", required=True, help="ruta a la base SQLite de origen")
    importer.add_argument("--dry-run", action="store_true")
    importer.add_argument("--json", action="store_true")
    importer.set_defaults(handler=_cmd_import)

    mcp = sub.add_parser("mcp", help="sirve MCP por stdio (JSON-RPC)")
    mcp.set_defaults(handler=_cmd_mcp)
    return p


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ns = _parser().parse_args(argv)
    try:
        return ns.handler(ns)
    except (ValueError, FileNotFoundError) as error:
        print(f"cairn: {error}", file=sys.stderr)
        return 1
    except sqlite3.DatabaseError as error:
        if any(
            word in str(error).lower()
            for word in ("not a database", "corrupt", "malformed")
        ):
            print(
                "cairn: base de datos corrupta; borra .cairn/cairn.db y ejecuta "
                "'cairn rebuild'",
                file=sys.stderr,
            )
        else:
            print(f"cairn: error de base de datos: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
