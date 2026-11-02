"""Servidor MCP por stdio (JSON-RPC 2.0 en NDJSON), sin dependencias.

Se apoya en el mismo Store que la CLI: el proceso es el único escritor
mientras vive, así que no hay arranque de Python por llamada.
"""

import json
import sys

from cairn_mem import __version__
from cairn_mem.anchor import resolve_anchor
from cairn_mem.paths import data_dir
from cairn_mem.render import render_l0
from cairn_mem.store import KINDS, Store

PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_PROTOCOLS = (PROTOCOL_VERSION, "2025-03-26", "2024-11-05")
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

TOOLS = [
    {
        "name": "save",
        "description": (
            "Guarda una memoria del proyecto. Mismo topic reemplaza la anterior."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": list(KINDS)},
                "title": {"type": "string"},
                "body": {"type": "string", "maxLength": 500},
                "why": {"type": "string"},
                "topic": {"type": "string"},
                "anchor": {"type": "string"},
            },
            "required": ["kind", "title", "body"],
            "additionalProperties": False,
        },
    },
    {
        "name": "search",
        "description": "Busca memorias activas por texto (BM25).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get",
        "description": "Devuelve una memoria completa por id.",
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "context",
        "description": "Memoria del proyecto (L0) para cargar al empezar.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]

INSTRUCTIONS = (
    "Memoria del proyecto. Busca antes de guardar; guarda solo decisiones, "
    "convenciones y gotchas con motivo. Mismo topic reemplaza la memoria anterior."
)


class Server:
    def __init__(self):
        self._store = None

    def store(self) -> Store:
        if self._store is None:
            self._store = Store(str(data_dir()))
        return self._store

    def handle(self, request):
        if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
            return _error(
                request.get("id") if isinstance(request, dict) else None,
                INVALID_REQUEST,
                "petición JSON-RPC inválida",
            )
        method = request.get("method")
        params = request.get("params") or {}
        if "id" not in request:
            return None  # notificación: no se responde
        request_id = request["id"]
        if not isinstance(method, str):
            return _error(request_id, INVALID_REQUEST, "falta method")
        if not isinstance(params, dict):
            return _error(request_id, INVALID_REQUEST, "params debe ser objeto")
        if method == "initialize":
            requested = params.get("protocolVersion")
            version = (
                requested if requested in SUPPORTED_PROTOCOLS else PROTOCOL_VERSION
            )
            return _result(
                request_id,
                {
                    "protocolVersion": version,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "cairn-mem", "version": __version__},
                    "instructions": INSTRUCTIONS,
                },
            )
        if method == "ping":
            return _result(request_id, {})
        if method == "tools/list":
            return _result(request_id, {"tools": TOOLS})
        if method == "tools/call":
            return self._call_tool(request_id, params)
        return _error(request_id, METHOD_NOT_FOUND, f"método desconocido: {method}")

    def _call_tool(self, request_id, params):
        if not isinstance(params, dict):
            return _error(request_id, INVALID_REQUEST, "params debe ser objeto")
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return _error(request_id, INVALID_REQUEST, "arguments debe ser objeto")
        tool = _TOOL_HANDLERS.get(name)
        if tool is None:
            return _error(request_id, INVALID_PARAMS, f"tool desconocida: {name}")
        try:
            text = tool(self, arguments)
        except (ValueError, TypeError, FileNotFoundError, OSError) as error:
            return _result(
                request_id,
                {
                    "content": [{"type": "text", "text": str(error)}],
                    "isError": True,
                },
            )
        return _result(request_id, {"content": [{"type": "text", "text": text}]})


def _save(server, args):
    kind = args.get("kind")
    title = args.get("title")
    body = args.get("body")
    missing = [
        key
        for key, value in (("kind", kind), ("title", title), ("body", body))
        if not isinstance(value, str) or not value
    ]
    if missing:
        raise ValueError(f"faltan argumentos: {', '.join(missing)}")
    anchor_path = anchor_hash = None
    if args.get("anchor"):
        anchor_path, anchor_hash = resolve_anchor(args["anchor"], data_dir().parent)
    memory_id = server.store().save(
        kind=kind,
        title=title,
        body=body,
        why=args.get("why"),
        topic_key=args.get("topic"),
        anchor_path=anchor_path,
        anchor_hash=anchor_hash,
    )
    return memory_id


def _search(server, args):
    query = args.get("query")
    if not isinstance(query, str) or not query:
        raise ValueError("falta el argumento: query")
    limit = args.get("limit", 5)
    if not isinstance(limit, int) or isinstance(limit, bool):
        raise TypeError("limit debe ser entero")
    limit = max(1, min(limit, 20))
    return json.dumps(server.store().search(query, limit=limit), ensure_ascii=False)


def _get(server, args):
    memory_id = args.get("id")
    if not isinstance(memory_id, str) or not memory_id:
        raise ValueError("falta el argumento: id")
    memory = server.store().get(memory_id)
    if memory is None:
        raise ValueError(f"no existe la memoria {memory_id}")
    return json.dumps(memory, ensure_ascii=False)


def _context(server, args):
    return render_l0(server.store())


_TOOL_HANDLERS = {"save": _save, "search": _search, "get": _get, "context": _context}


def _result(request_id, value):
    return {"jsonrpc": "2.0", "id": request_id, "result": value}


def _error(request_id, code, message):
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _write(stream, message) -> bool:
    try:
        stream.write(json.dumps(message, ensure_ascii=False).encode("utf-8") + b"\n")
        stream.flush()
    except (BrokenPipeError, OSError):
        return False  # el arnés cerró el pipe: se apaga sin ruido
    return True


def serve(stdin=None, stdout=None) -> int:
    """Lee NDJSON de stdin y responde por stdout hasta EOF."""
    source = stdin if stdin is not None else sys.stdin.buffer
    target = stdout if stdout is not None else sys.stdout.buffer
    server = Server()
    for raw in source:
        line = raw.strip()
        if not line:
            continue
        try:
            request = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            if not _write(target, _error(None, PARSE_ERROR, "JSON inválido")):
                return 0
            continue
        try:
            response = server.handle(request)
        except Exception as error:  # noqa: BLE001 — el servidor no debe morir por una tool
            print(f"cairn mcp: {error}", file=sys.stderr)
            response = _error(
                request.get("id") if isinstance(request, dict) else None,
                INTERNAL_ERROR,
                "error interno",
            )
        if response is not None and not _write(target, response):
            return 0
    return 0
