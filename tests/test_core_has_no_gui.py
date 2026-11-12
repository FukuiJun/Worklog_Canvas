"""仕様8章「保守性」: データ処理は画面なしでテストできる（core は PySide6 を import しない）。"""
import ast
from pathlib import Path

CORE = Path(__file__).resolve().parents[1] / "worklog_canvas" / "core"


def test_core_does_not_import_qt():
    for py in CORE.glob("*.py"):
        tree = ast.parse(py.read_text("utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            assert not any(n.split(".")[0] in ("PySide6", "PyQt5", "PyQt6") for n in names), py.name
