import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from worklog_canvas.core.repository import DataFolder  # noqa: E402

SAMPLE_DIR = ROOT / "sample_data"


@pytest.fixture
def data_folder(tmp_path) -> DataFolder:
    return DataFolder(tmp_path / "data")


@pytest.fixture
def sample_folder(tmp_path) -> DataFolder:
    """sample_data のコピー（テストで書き換えても元は変わらない）。"""
    dst = tmp_path / "sample"
    shutil.copytree(SAMPLE_DIR, dst)
    return DataFolder(dst)
