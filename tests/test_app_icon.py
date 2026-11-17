"""アプリのアイコン（exe とウィンドウ）。"""
import struct
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from worklog_canvas.ui import theme

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packaging"))
import build_exe  # noqa: E402


def _ico_sizes(path: Path) -> set[int]:
    data = path.read_bytes()
    reserved, kind, count = struct.unpack_from("<HHH", data, 0)
    assert (reserved, kind) == (0, 1)
    sizes = set()
    for i in range(count):
        w = data[6 + 16 * i]
        sizes.add(w or 256)
    return sizes


def test_ico_has_windows_sizes():
    assert theme.ICON_FILE.exists()
    assert {16, 24, 32, 48, 256} <= _ico_sizes(theme.ICON_FILE)


def test_window_icon_is_set():
    app = QApplication.instance() or QApplication([])
    theme.apply(app)
    icon = app.windowIcon()
    assert not icon.isNull()
    assert icon.pixmap(32, 32).toImage().hasAlphaChannel()  # 背景透過


def test_exe_build_uses_icon():
    args = build_exe.PYINSTALLER_ARGS
    assert args[args.index("--icon") + 1] == str(theme.ICON_FILE)
    assert any(str(theme.ICON_FILE) in a and "worklog_canvas/ui/resources" in a for a in args)
