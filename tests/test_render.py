"""Tests de M2: L0 con presupuesto, determinista y con marca de stale."""

from cairn_mem import render
from cairn_mem.store import Store


def _fill(store, n, kind="fact"):
    for i in range(n):
        store.save(kind=kind, title=f"{kind} {i}", body="detalle " * 30)


def test_l0_respects_char_budget(tmp_path):
    s = Store(str(tmp_path / ".cairn"))
    _fill(s, 200)
    assert len(render.render_l0(s, max_chars=3000)) <= 3000


def test_l0_is_deterministic(tmp_path):
    s = Store(str(tmp_path / ".cairn"))
    _fill(s, 20)
    assert render.render_l0(s) == render.render_l0(s)


def test_l0_orders_by_kind_priority(tmp_path):
    s = Store(str(tmp_path / ".cairn"))
    s.save(kind="fact", title="F", body="x")
    s.save(kind="convention", title="C", body="x")
    out = render.render_l0(s)
    assert out.index("C") < out.index("F")


def test_l0_reserves_room_for_each_kind(tmp_path):
    """30 decisiones nuevas no pueden expulsar del L0 el resto de kinds."""
    s = Store(str(tmp_path / ".cairn"))
    s.save(kind="gotcha", title="Trampa del proxy", body="60s corta las subidas")
    s.save(kind="fact", title="Puerto de Vite", body="5173")
    s.save(kind="convention", title="Ramas con prefijo", body="feat/ y fix/")
    _fill(s, 30, "decision")
    out = render.render_l0(s)
    for title in ("Trampa del proxy", "Puerto de Vite", "Ramas con prefijo"):
        assert title in out


def test_l0_mixes_kinds_within_budget(tmp_path):
    s = Store(str(tmp_path / ".cairn"))
    for kind in ("decision", "convention", "gotcha", "fact"):
        _fill(s, 60, kind)
    out = render.render_l0(s, max_chars=3000)
    assert len(out) <= 3000
    for kind in ("decision", "convention", "gotcha", "fact"):
        assert any(f"] {kind}: " in line for line in out.splitlines())


def test_l0_keeps_one_line_per_memory(tmp_path):
    s = Store(str(tmp_path / ".cairn"))
    s.save(kind="fact", title="uno\ndos", body="x")
    lines = render.render_l0(s).splitlines()
    assert len(lines) == 2 and lines[1].startswith("- [")


def test_l0_marks_stale(tmp_path):
    root = tmp_path
    (root / "a.py").write_text("v1\n", encoding="utf-8")
    from cairn_mem.anchor import file_hash

    s = Store(str(root / ".cairn"))
    s.save(
        kind="gotcha",
        title="G",
        body="x",
        anchor_path="a.py",
        anchor_hash=file_hash(str(root / "a.py")),
    )
    (root / "a.py").write_text("v2\n", encoding="utf-8")
    assert "⚠" in render.render_l0(s, project_root=str(root))


def test_l0_shows_topic_key_when_present(tmp_path):
    s = Store(str(tmp_path / ".cairn"))
    mid = s.save(
        kind="decision", topic_key="storage/fts5", title="Usar FTS5", body="bm25"
    )
    assert f"- [{mid}] decision: [storage/fts5] Usar FTS5" in render.render_l0(s)


def test_l0_without_topic_keeps_the_existing_format(tmp_path):
    s = Store(str(tmp_path / ".cairn"))
    mid = s.save(kind="fact", title="Sin topic", body="x")
    assert f"- [{mid}] fact: Sin topic — x" in render.render_l0(s)


def test_l0_budget_holds_with_topic_keys(tmp_path):
    s = Store(str(tmp_path / ".cairn"))
    for i in range(200):
        s.save(
            kind="fact",
            topic_key=f"area/{i}",
            title=f"memoria {i}",
            body="detalle " * 30,
        )
    assert len(render.render_l0(s, max_chars=3000)) <= 3000
