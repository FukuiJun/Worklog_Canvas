"""WorklogCanvas.exe を作る（build.bat と GitHub Actions の両方から使う）。

    python packaging/build_exe.py [--version 1.2.0] [--zip 出力.zip] [--skip-self-test]

1. （--version があれば）worklog_canvas/__init__.py の __version__ をその値にする
2. PyInstaller で dist/WorklogCanvas/WorklogCanvas.exe を作る（1フォルダ形式）
3. できた exe を --self-test で起動し、同梱した部品が動くことを確かめる
4. （--zip があれば）dist/WorklogCanvas フォルダを zip にする
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME = "WorklogCanvas"
DIST = ROOT / "dist" / NAME
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")

PYINSTALLER_ARGS = [
    "--noconfirm", "--clean", "--onedir", "--windowed", "--name", NAME, "--paths", str(ROOT),
    "--collect-all", "icalendar", "--collect-all", "recurring_ical_events", "--collect-all", "x_wr_timezone",
    "--collect-data", "tzdata",
    "--exclude-module", "tkinter", "--exclude-module", "pytest", "--exclude-module", "icalendar.tests",
    "--distpath", str(ROOT / "dist"), "--workpath", str(ROOT / "build"), "--specpath", str(ROOT / "build"),
    str(ROOT / "packaging" / f"{NAME}.py"),
]


def set_version(version: str) -> None:
    if not VERSION_RE.match(version):
        raise SystemExit(f"版番号は 1.2.3 の形にしてください: {version!r}")
    init = ROOT / "worklog_canvas" / "__init__.py"
    text = init.read_text("utf-8")
    new, n = re.subn(r'^__version__ = "[^"]*"', f'__version__ = "{version}"', text, flags=re.M)
    if n != 1:
        raise SystemExit("worklog_canvas/__init__.py に __version__ が見つかりません")
    init.write_text(new, encoding="utf-8")
    print(f"版番号: {version}")


def build() -> Path:
    import PyInstaller.__main__
    PyInstaller.__main__.run(PYINSTALLER_ARGS)
    exe = DIST / (f"{NAME}.exe" if os.name == "nt" else NAME)
    if not exe.exists():
        raise SystemExit(f"exe ができていません: {exe}")
    return exe


def self_test(exe: Path) -> None:
    """できた exe を --self-test で起動する。結果は一時フォルダの selftest.txt から読む。"""
    home = Path(tempfile.mkdtemp(prefix="wc_selftest_home_"))
    env = dict(os.environ, WORKLOG_CANVAS_HOME=str(home))
    env.setdefault("QT_QPA_PLATFORM", "offscreen")  # 画面のない環境（GitHub Actions など）でも動かす
    proc = subprocess.run([str(exe), "--self-test"], env=env, timeout=300)
    report = home / "selftest.txt"
    print(report.read_text("utf-8") if report.exists() else "（selftest.txt が作られていません）")
    shutil.rmtree(home, ignore_errors=True)
    if proc.returncode != 0:
        raise SystemExit(f"exe の動作確認に失敗しました（終了コード {proc.returncode}）")


def make_zip(path: Path) -> None:
    """dist/WorklogCanvas フォルダを、展開すると WorklogCanvas フォルダができる zip にする。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(DIST.rglob("*")):
            if f.is_file():
                z.write(f, Path(NAME) / f.relative_to(DIST))
    print(f"zip を作りました: {path}（{path.stat().st_size / 1e6:.1f} MB）")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", help="版番号（例: 1.2.0）。指定すると exe に入れる")
    ap.add_argument("--zip", type=Path, help="できたフォルダを zip にする出力先")
    ap.add_argument("--skip-self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.version:
        set_version(a.version)
    exe = build()
    if not a.skip_self_test:
        self_test(exe)
    if a.zip:
        make_zip(a.zip)
    print(f"完成しました: {exe}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
