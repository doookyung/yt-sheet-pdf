#!/bin/bash
# 최초 1회 설치: ./setup.sh   (끝나면 GUI 앱이 자동으로 열립니다)
set -e
cd "$(dirname "$0")"

# 런처가 찾아둔 python 경로가 있으면 우선 사용 (더블클릭 시 PATH 가 비어 있음)
PY=""
if [ -f .python-path ] && [ -x "$(cat .python-path)" ]; then
  PY="$(cat .python-path)"
elif command -v python3 >/dev/null; then
  PY="$(command -v python3)"
else
  for c in /Library/Frameworks/Python.framework/Versions/3.1[0-9]/bin/python3 /opt/homebrew/bin/python3 /usr/local/bin/python3; do
    [ -x "$c" ] && PY="$c" && break
  done
fi
if [ -z "$PY" ]; then
  echo "python3 가 없습니다. https://www.python.org/downloads/ 에서 설치 후 다시 실행하세요."; exit 1
fi
echo "Python: $PY"
echo "설치 중… (1~2분)"
"$PY" -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
rm -f .python-path
echo
echo "설치 완료! 앱을 엽니다. 다음부터는 '악보PDF.app' 을 더블클릭하세요."
echo "  (터미널 사용법: ./sheet2pdf \"유튜브링크\")"
.venv/bin/python app.py >/dev/null 2>&1 &
