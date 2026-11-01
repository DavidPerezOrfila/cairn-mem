"""Store: events.jsonl (verdad) + SQLite FTS5 (derivado). Implementar en M1.

API esperada por los tests:
  Store(root)                         # root = carpeta .cairn
  .save(kind, title, body, why=None, topic_key=None, anchor_path=None, anchor_hash=None, id=None) -> id
  .get(id) -> dict | None
  .search(query, limit=5) -> list[{id, kind, title, snippet}]
  .archive(id)
  .rebuild()
  .dump() -> list[dict]               # estado de la tabla mem, ordenado, para comparar
"""


class Store:
    def __init__(self, root: str):
        raise NotImplementedError("M1")
