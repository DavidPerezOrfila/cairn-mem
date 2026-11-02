"""CLI de cairn-mem (M1)."""

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

from cairn_mem.anchor import is_stale, resolve_anchor
from cairn_mem.paths import data_dir
from cairn_mem.store import KINDS, Store

GITIGNORE = ("cairn.db", "cairn.db-*", "MEMORY.md")


def _print_json(value) -> None:
    print(json.dumps(value, ensure_ascii=False))


def _cmd_init(ns) -> int:
    env = os.environ.get("CAIRN_DIR")
    root = Path(env) if env else Path.cwd() / ".cairn"
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
        anchor_path, anchor_hash = resolve_anchor(ns.anchor, data_dir().parent)
    mid = Store(str(data_dir())).save(
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
    results = Store(str(data_dir())).search(ns.query, limit=ns.limit)
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
    memory = Store(str(data_dir())).get(ns.id)
    if memory is None:
        raise ValueError(f"no existe la memoria {ns.id}")
    if ns.json:
        _print_json(memory)
    else:
        for key, value in memory.items():
            if value is not None:
                print(f"{key}: {value}")
    return 0


def _cmd_archive(ns) -> int:
    store = Store(str(data_dir()))
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
    save.add_argument("--json", action="store_true")
    save.set_defaults(handler=_cmd_save)

    search = sub.add_parser("search", help="busca memorias activas")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=5)
    search.add_argument("--json", action="store_true")
    search.set_defaults(handler=_cmd_search)

    get = sub.add_parser("get", help="muestra una memoria completa")
    get.add_argument("id")
    get.add_argument("--json", action="store_true")
    get.set_defaults(handler=_cmd_get)

    archive = sub.add_parser("archive", help="archiva una memoria")
    archive.add_argument("id")
    archive.set_defaults(handler=_cmd_archive)

    rebuild = sub.add_parser("rebuild", help="reconstruye la DB desde events.jsonl")
    rebuild.set_defaults(handler=_cmd_rebuild)

    render = sub.add_parser("render", help="regenera y muestra MEMORY.md (L0)")
    render.set_defaults(handler=_cmd_render)

    check = sub.add_parser("check", help="lista memorias con ancla stale")
    check.add_argument("--json", action="store_true")
    check.set_defaults(handler=_cmd_check)

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
    except sqlite3.Error:
        print("cairn: error de base de datos; ejecuta 'cairn rebuild'", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
