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


@pytest.fixture(autouse=True)
def _no_blocking_dialogs(monkeypatch, request):
    """テスト中に想定外のメッセージボックスが開いて止まらないようにする。

    画面のないテストでは、閉じる人がいないので開いたまま待ち続けてしまう（CIが時間切れになる）。
    代わりに既定の答えを返して記録し、テストを失敗にする。メッセージを確かめるテストは、
    自分で QMessageBox.warning などを差し替える（後から差し替えた方が優先される）。
    """
    try:
        from PySide6.QtWidgets import QMessageBox
    except ImportError:
        yield
        return
    shown = []

    def fake(kind, answer):
        def f(*args, **kwargs):
            shown.append(f"{kind}: {args[2] if len(args) > 2 else ''}")
            return answer
        return f

    monkeypatch.setattr(QMessageBox, "warning", fake("warning", QMessageBox.Ok))
    monkeypatch.setattr(QMessageBox, "critical", fake("critical", QMessageBox.Ok))
    monkeypatch.setattr(QMessageBox, "information", fake("information", QMessageBox.Ok))
    monkeypatch.setattr(QMessageBox, "question", fake("question", QMessageBox.No))
    yield
    if shown:
        pytest.fail("想定外のメッセージボックスが表示されました: " + " / ".join(shown))
