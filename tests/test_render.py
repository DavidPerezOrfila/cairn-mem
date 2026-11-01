"""Tests de M2: L0 con presupuesto, determinista y con marca de stale."""

import pytest

render = pytest.importorskip("cairn_mem.render", reason="M2 pendiente")
from cairn_mem.store import Store


def _fill(store, n):
    for i in range(n):
        store.save(kind="fact", title=f"hecho {i}", body="detalle " * 30)


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
