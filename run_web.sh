#!/usr/bin/env bash
# 웹 UI 실행 (로컬/LAN). 브라우저에서 http://localhost:8501 접속.
# 서버 설정은 .streamlit/config.toml 참조.
set -euo pipefail
cd "$(dirname "$0")"

# Ensure Homebrew path is in PATH on macOS
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"


VENV=".venv"
if [ ! -d "$VENV" ]; then
  echo "[run_web] .venv 없음 → 생성 및 의존성 설치"
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install --upgrade pip
  "$VENV/bin/pip" install -r requirements.txt
fi

# 8501 포트 이미 사용 중이면 자동 종료
if lsof -ti :8501 &>/dev/null; then
  echo "[run_web] 포트 8501 사용 중 → 기존 프로세스 종료"
  lsof -ti :8501 | xargs kill -9
  sleep 0.5
fi

echo "[run_web] Streamlit 시작 → http://localhost:8501 (종료: Ctrl+C)"
exec "$VENV/bin/streamlit" run ui/app.py
