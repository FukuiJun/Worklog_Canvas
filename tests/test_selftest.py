"""exe の動作確認（--self-test）がこの環境で成功すること。"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets")
pytest.importorskip("openpyxl")
pytest.importorskip("icalendar")


def test_self_test(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("WORKLOG_CANVAS_HOME", str(tmp_path))
    from worklog_canvas import selftest
    assert selftest.run() == 0
    assert "成功" in (tmp_path / "selftest.txt").read_text("utf-8")


def test_build_script_version_check(tmp_path, monkeypatch):
    """リリースの版番号は 1.2.3 の形だけを受け付ける（タグ v1.2.3 から作る）。"""
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "build_exe", Path(__file__).resolve().parents[1] / "packaging" / "build_exe.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    init = tmp_path / "worklog_canvas" / "__init__.py"
    init.parent.mkdir()
    init.write_text('"""x"""\n\n__version__ = "0.1.0"  # コメント\n', encoding="utf-8")
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    mod.set_version("1.2.0")
    assert '__version__ = "1.2.0"' in init.read_text("utf-8")
    with pytest.raises(SystemExit):
        mod.set_version("v1.2")
