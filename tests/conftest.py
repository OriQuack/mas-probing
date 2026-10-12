"""Test environment. Tests needing the Landlock sandbox or the local GAIA data are skipped (with the reason) where
those are missing. Tests never write to the experiment's shared tool cache."""

from __future__ import annotations

import pytest

from minpilot.data.gaia import GAIA_ROOT, GaiaTask
from minpilot.tools.sandbox import landlock_abi

HAVE_LANDLOCK = landlock_abi() >= 4
HAVE_GAIA = (GAIA_ROOT / "validation" / "metadata.parquet").exists()


def pytest_configure(config):
    config.addinivalue_line("markers", "landlock: needs the Landlock code sandbox (Linux >= 6.7, ABI 4)")
    config.addinivalue_line("markers", "gaia_data: needs the local GAIA validation metadata")


def pytest_collection_modifyitems(config, items):
    for item in items:
        if "landlock" in item.keywords and not HAVE_LANDLOCK:
            item.add_marker(pytest.mark.skip(reason="Landlock ABI >= 4 not available"))
        if "gaia_data" in item.keywords and not HAVE_GAIA:
            item.add_marker(pytest.mark.skip(reason="GAIA validation metadata not present"))


@pytest.fixture(scope="session", autouse=True)
def _real_tool_cache_untouched():
    from minpilot.tools.config import ToolConfig

    path = ToolConfig().cache_path

    def state():
        return path.stat().st_mtime_ns if path.exists() else None

    before = state()
    yield
    assert state() == before, f"a test wrote to the real tool cache {path}"


class CharEncoding:
    """Stand-in for tiktoken's cl100k_base (one token per character), so tests need no download."""

    def encode(self, text: str) -> list[int]:
        return [ord(c) for c in text]

    def decode(self, tokens: list[int]) -> str:
        return "".join(map(chr, tokens))


@pytest.fixture(scope="session", autouse=True)
def _offline_reader_encoding():
    from minpilot.tools import reader

    reader._ENCODINGS["cl100k_base"] = CharEncoding()
    yield
    reader._ENCODINGS.pop("cl100k_base", None)


@pytest.fixture
def task(tmp_path) -> GaiaTask:
    att = tmp_path / "data" / "sheet.csv"
    att.parent.mkdir()
    att.write_text("order_id,date,amount\n1,2025-01-02,10\n1,2025-01-02,5\n2,2025-02-01,7\n")
    return GaiaTask(task_id="t-0001", level=2, question="How many unique orders were placed in 2025?",
                    file_name="sheet.csv", file_path=att)
