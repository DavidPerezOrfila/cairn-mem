"""Tests de M2: anclas y stale calculado al leer."""

import pytest

from cairn_mem import anchor


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
    with pytest.raises(ValueError, match="dentro del proyecto"):
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
    with pytest.raises(ValueError, match="demasiado grande"):
        anchor.resolve_anchor(str(big), tmp_path)


def test_stale_reuses_the_hash_while_the_file_does_not_change(tmp_path, monkeypatch):
    """El L0 revisa todas las anclas tras cada save: sin caché cada una se relee."""
    target = tmp_path / "a.py"
    target.write_text("v1\n", encoding="utf-8")
    digest = anchor.file_hash(target)
    calls = []
    real = anchor.file_hash

    def counted(path):
        calls.append(1)
        return real(path)

    monkeypatch.setattr(anchor, "file_hash", counted)
    assert anchor.is_stale("a.py", digest, str(tmp_path)) is False
    assert anchor.is_stale("a.py", digest, str(tmp_path)) is False
    assert len(calls) == 1
    target.write_text("v2\n", encoding="utf-8")
    assert anchor.is_stale("a.py", digest, str(tmp_path)) is True
    assert len(calls) == 2
