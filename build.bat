@echo off
rem ============================================================
rem  Worklog Canvas の exe を作る（PyInstaller、1フォルダ形式）
rem    build.bat          テストを実行してから exe を作る
rem    build.bat /notest  テストを省略する
rem  できあがり: dist\WorklogCanvas\WorklogCanvas.exe
rem  （dist\WorklogCanvas フォルダごと配布する。Python のインストールは不要）
rem  ※ GitHub で v1.2.0 のようなタグをプッシュすると、同じ手順で作った zip が
rem    Release に自動で添付される（.github\workflows\release.yml）
rem ============================================================
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  echo [エラー] Python ランチャー（py）が見つかりません。Python 3.12 をインストールしてください。
  exit /b 1
)
py -3.12 -c "import sys" >nul 2>nul
if errorlevel 1 (
  echo [エラー] Python 3.12 が見つかりません。Python 3.12 をインストールしてください。
  exit /b 1
)

if not exist ".venv-build\Scripts\python.exe" (
  echo ビルド用の仮想環境を作成しています...
  py -3.12 -m venv .venv-build || exit /b 1
)
set PY=.venv-build\Scripts\python.exe

echo 必要なライブラリを入れています...
"%PY%" -m pip install --upgrade pip >nul
"%PY%" -m pip install -r requirements.txt || exit /b 1

if /i not "%~1"=="/notest" (
  echo 自動テストを実行しています...
  "%PY%" -m pytest -q || (
    echo [エラー] 自動テストに失敗しました。exe は作成していません。
    exit /b 1
  )
)

echo exe を作成し、動作を確認しています...
"%PY%" packaging\build_exe.py || (
  echo [エラー] exe の作成または動作確認に失敗しました。
  exit /b 1
)
exit /b 0
