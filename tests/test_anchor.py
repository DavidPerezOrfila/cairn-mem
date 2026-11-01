"""Tests de M2: anclas y stale calculado al leer."""
import pytest

anchor = pytest.importorskip("cairn_mem.anchor", reason="M2 pendiente")


def test_hash_ignores_crlf(tmp_path):
    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    a.write_bytes(b"x\ny\n")
    b.write_bytes(b"x\r\ny\r\n")
    assert anchor.file_hash(str(a)) == anchor.file_hash(str(b))


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
