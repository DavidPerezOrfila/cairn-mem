"""La versión publicada y la del paquete no pueden divergir."""

import re
from pathlib import Path

from cairn_mem import __version__

PYPROJECT = Path(__file__).parents[1] / "pyproject.toml"


def test_version_matches_pyproject():
    text = PYPROJECT.read_text(encoding="utf-8")
    declared = re.search(r'^version = "([^"]+)"', text, re.MULTILINE).group(1)
    assert declared == __version__
