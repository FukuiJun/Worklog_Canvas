"""アイコンの元絵（SVG）から Windows 用の app_icon.ico を作る。

    python scripts/make_icon.py

worklog_canvas/ui/resources/app_icon.svg を 16〜256px の各サイズで描き、
PNG を詰めた .ico（Windows Vista 以降の形式）として同じフォルダに保存する。
SVG を直したときだけ実行し、できた .ico もコミットする。
"""
from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage, QPainter  # noqa: E402
from PySide6.QtSvg import QSvgRenderer  # noqa: E402

RES = Path(__file__).resolve().parents[1] / "worklog_canvas" / "ui" / "resources"
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def render_png(renderer: QSvgRenderer, size: int) -> bytes:
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    renderer.render(p)
    p.end()
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(data)


def build_ico(pngs: list[tuple[int, bytes]]) -> bytes:
    head = struct.pack("<HHH", 0, 1, len(pngs))
    offset = 6 + 16 * len(pngs)
    entries, blobs = b"", b""
    for size, png in pngs:
        s = 0 if size >= 256 else size  # 256 は 0 と書く決まり
        entries += struct.pack("<BBBBHHII", s, s, 0, 0, 1, 32, len(png), offset)
        blobs += png
        offset += len(png)
    return head + entries + blobs


def main() -> int:
    _app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    renderer = QSvgRenderer(str(RES / "app_icon.svg"))
    if not renderer.isValid():
        raise SystemExit("app_icon.svg を読めません")
    ico = build_ico([(s, render_png(renderer, s)) for s in SIZES])
    (RES / "app_icon.ico").write_bytes(ico)
    print(f"作りました: {RES / 'app_icon.ico'}（{len(ico)} バイト）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
