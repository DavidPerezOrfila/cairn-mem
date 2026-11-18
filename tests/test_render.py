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
    assert lines[:2] == [render.TITLE, render.HEADER]
    assert len(lines) == 3 and lines[2].startswith("- [")


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


def test_stale_marker_counts_against_the_budget(tmp_path):
    """La marca ⚠ es parte de la línea: si la empuja fuera, la memoria no entra."""
    from cairn_mem.anchor import file_hash

    (tmp_path / "a.py").write_text("v1\n", encoding="utf-8")
    s = Store(str(tmp_path / ".cairn"))
    s.save(
        kind="gotcha",
        title="G",
        body="x",
        anchor_path="a.py",
        anchor_hash=file_hash(tmp_path / "a.py"),
    )
    (tmp_path / "a.py").write_text("v2\n", encoding="utf-8")

    full = render.render_l0(s, max_chars=10_000)
    line = full.splitlines()[2]
    assert line.endswith(render.STALE_MARK)
    head = f"{render.TITLE}\n{render.HEADER}\n"
    threshold = len(head) + len(line) + 1

    assert render.render_l0(s, max_chars=threshold - 1) == head
    assert (
        render.render_l0(s, max_chars=threshold)
        .splitlines()[2]
        .endswith(render.STALE_MARK)
    )


def test_l0_marks_missing_and_oversized_anchors_in_the_parallel_path(tmp_path):
    """Con 2+ anclas el render usa el pool: un fichero ausente y uno > 2 MB no
    rompen el render y se marcan stale, como en el camino secuencial."""
    from cairn_mem.anchor import MAX_HASH_BYTES, file_hash

    big = tmp_path / "big.csv"
    big.write_bytes(b"x" * (MAX_HASH_BYTES + 1))
    s = Store(str(tmp_path / ".cairn"))
    s.save(
        kind="fact",
        title="ancla ausente",
        body="x",
        anchor_path="missing.py",
        anchor_hash="0" * 40,
    )
    s.save(
        kind="fact",
        title="ancla enorme",
        body="x",
        anchor_path="big.csv",
        anchor_hash=file_hash(big),
    )
    out = render.render_l0(s)
    assert "ancla ausente" in out and "ancla enorme" in out
    assert out.count(render.STALE_MARK) == 2
