@echo off
rem ============================================================
rem  Worklog Canvas の exe を作る（PyInstaller、1フォルダ形式）
rem    build.bat          テストを実行してから exe を作る
rem    build.bat /notest  テストを省略する
rem  できあがり: dist\WorklogCanvas\WorklogCanvas.exe
rem  （dist\WorklogCanvas フォルダごと配布する。Python のインストールは不要）
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

echo exe を作成しています...
"%PY%" -m PyInstaller --noconfirm --clean --onedir --windowed --name WorklogCanvas --paths . ^
  --collect-all icalendar --collect-all recurring_ical_events --collect-all x_wr_timezone ^
  --collect-data tzdata ^
  --exclude-module tkinter --exclude-module pytest --exclude-module icalendar.tests ^
  packaging\WorklogCanvas.py || exit /b 1

echo できた exe の動作を確認しています...
start "" /wait "dist\WorklogCanvas\WorklogCanvas.exe" --self-test
if errorlevel 1 (
  echo [エラー] 動作確認に失敗しました。内容: %APPDATA%\WorklogCanvas\selftest.txt
  type "%APPDATA%\WorklogCanvas\selftest.txt"
  exit /b 1
)
type "%APPDATA%\WorklogCanvas\selftest.txt"
echo.
echo 完成しました: dist\WorklogCanvas\WorklogCanvas.exe
exit /b 0
