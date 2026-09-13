@echo off
chcp 65001 >nul
cd /d "%~dp0"
where python >nul 2>nul || (
  echo Python 3.10 이상이 필요합니다. https://www.python.org/downloads/ 에서 설치할 때 "Add python.exe to PATH" 를 꼭 체크하세요.
  start https://www.python.org/downloads/
  pause
  exit /b 1
)
if not exist .venv\Scripts\python.exe (
  echo 처음 실행입니다. 필요한 구성요소를 설치합니다 ^(1~2분^)...
  python -m venv .venv
  .venv\Scripts\pip install -q -r requirements.txt
)
start "" .venv\Scripts\pythonw.exe app.py
