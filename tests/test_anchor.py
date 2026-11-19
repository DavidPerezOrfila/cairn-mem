"""Tests de M2: anclas y stale calculado al leer."""

import pytest

from cairn_mem import anchor, render


def test_hash_ignores_crlf(tmp_path):
    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    a.write_bytes(b"x\ny\n")
    b.write_bytes(b"x\r\ny\r\n")
    assert anchor.file_hash(str(a)) == anchor.file_hash(str(b))


def test_large_anchor_is_stale_without_hashing(tmp_path, monkeypatch):
    big = tmp_path / "dump.csv"
    big.write_text("x" * 32, encoding="utf-8")
    digest = anchor.file_hash(big)
    monkeypatch.setattr(anchor, "MAX_HASH_BYTES", 10)
    assert anchor.is_stale("dump.csv", digest, str(tmp_path)) is True
    monkeypatch.setattr(anchor, "MAX_HASH_BYTES", 10_000)
    assert anchor.is_stale("dump.csv", digest, str(tmp_path)) is False


def test_stale_when_changed_or_missing(tmp_path):
    f = tmp_path / "f.py"
    f.write_text("v1\n", encoding="utf-8")
    h = anchor.file_hash(str(f))
    assert anchor.is_stale("f.py", h, str(tmp_path)) is False
    f.write_text("v2\n", encoding="utf-8")
    assert anchor.is_stale("f.py", h, str(tmp_path)) is True
    f.unlink()
    assert anchor.is_stale("f.py", h, str(tmp_path)) is True


def test_no_anchor_is_never_stale(tmp_path):
    assert anchor.is_stale(None, None, str(tmp_path)) is False


def test_resolve_anchor_rejects_paths_outside_project(tmp_path):
    (tmp_path / "project").mkdir()
    outside = tmp_path / "secret.key"
    outside.write_text("x\n", encoding="utf-8")
    with pytest.raises(ValueError, match="inside the project"):
        anchor.resolve_anchor(str(outside), tmp_path / "project")


def test_resolve_anchor_returns_posix_relative(tmp_path):
    target = tmp_path / "src" / "a.py"
    target.parent.mkdir()
    target.write_text("x\n", encoding="utf-8")
    relative, digest = anchor.resolve_anchor(str(target), tmp_path)
    assert relative == "src/a.py"
    assert digest == anchor.file_hash(target)


def test_resolve_anchor_rejects_a_file_over_the_hash_limit(tmp_path, monkeypatch):
    big = tmp_path / "dump.csv"
    big.write_text("x" * 32, encoding="utf-8")
    monkeypatch.setattr(anchor, "MAX_HASH_BYTES", 10)
    with pytest.raises(ValueError, match="too large"):
        anchor.resolve_anchor(str(big), tmp_path)


def test_stale_reads_an_anchor_once_per_render(tmp_path, monkeypatch):
    """El L0 revisa todas las anclas tras cada save: dos memorias sobre el mismo
    fichero no deben hashearlo dos veces."""
    from cairn_mem.render import render_l0
    from cairn_mem.store import Store

    store = Store(str(tmp_path / ".cairn"))
    (tmp_path / "a.py").write_text("v1\n", encoding="utf-8")
    digest = anchor.file_hash(tmp_path / "a.py")
    store.save(
        kind="fact", title="uno", body="a", anchor_path="a.py", anchor_hash=digest
    )
    store.save(
        kind="fact", title="dos", body="b", anchor_path="a.py", anchor_hash=digest
    )
    calls = []
    real = anchor.file_hash

    def counted(path):
        calls.append(path)
        return real(path)

    monkeypatch.setattr(anchor, "file_hash", counted)

    assert render.STALE_MARK not in render_l0(store)
    assert len(calls) == 1


def test_stale_detects_a_same_size_rewrite(tmp_path):
    """En NTFS la mtime se actualiza tarde: un hash viejo no se puede reutilizar
    solo porque (size, mtime_ns) coincidan."""
    target = tmp_path / "f.py"
    target.write_text("v1\n", encoding="utf-8")
    digest = anchor.file_hash(target)
    target.write_text("v2\n", encoding="utf-8")  # mismo tamaño
    assert anchor.is_stale("f.py", digest, str(tmp_path)) is True


def test_parallel_prewarm_hashes_each_anchor_once_per_render(tmp_path, monkeypatch):
    """Con varias anclas, el render las lee en paralelo: una vez por fichero y
    render, nunca entre comandos (la mtime de NTFS llega tarde)."""
    import cairn_mem.render as render_module
    from cairn_mem.render import render_l0
    from cairn_mem.store import Store

    store = Store(str(tmp_path / ".cairn"))
    for name in ("a.py", "b.py"):
        (tmp_path / name).write_text(f"{name} v1\n", encoding="utf-8")
        store.save(
            kind="fact",
            title=f"memoria {name}",
            body="x",
            anchor_path=name,
            anchor_hash=anchor.file_hash(tmp_path / name),
        )
    calls = []
    real = render_module.file_hash

    def counted(path):
        calls.append(str(path))
        return real(path)

    monkeypatch.setattr(render_module, "file_hash", counted)
    (tmp_path / "b.py").write_text("b.py v2\n", encoding="utf-8")

    out = render_l0(store)
    assert out.count(render.STALE_MARK) == 1
    assert len(calls) == 2

    render_l0(store)
    assert len(calls) == 4  # sin caché entre renders
