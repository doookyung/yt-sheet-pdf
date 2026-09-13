#!/bin/bash
# 최초 1회 설치: ./setup.sh
set -e
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null; then
  echo "python3 가 없습니다. https://www.python.org/downloads/ 에서 설치 후 다시 실행하세요."; exit 1
fi
python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
echo
echo "설치 완료! 사용법:"
echo '  ./sheet2pdf "https://www.youtube.com/watch?v=XXXX"'
