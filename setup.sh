#!/bin/bash
# 최초 1회 설치: ./setup.sh   (끝나면 GUI 앱이 자동으로 열립니다)
set -e
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null; then
  echo "python3 가 없습니다. https://www.python.org/downloads/ 에서 설치 후 다시 실행하세요."; exit 1
fi
echo "설치 중… (1~2분)"
python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
echo
echo "설치 완료! 앱을 엽니다. 다음부터는 '악보PDF.app' 을 더블클릭하세요."
echo "  (터미널 사용법: ./sheet2pdf \"유튜브링크\")"
.venv/bin/python app.py >/dev/null 2>&1 &
