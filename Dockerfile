# 자체 호스팅 웹 환경 (로컬/사내 서버). 원본 영상은 컨테이너 밖 볼륨에 보관.
FROM python:3.11-slim

# 시스템 의존성: ffmpeg/ffprobe(정규화·클립), OpenCV 런타임 라이브러리
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 의존성 먼저 설치(레이어 캐시)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스 복사 (data/, models/는 볼륨으로 마운트 — 이미지에 영상 포함 안 함)
COPY src/ ./src/
COPY ui/ ./ui/
COPY config.yaml .
COPY .streamlit/ ./.streamlit/

EXPOSE 8501

# 컨테이너 헬스체크
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')" || exit 1

CMD ["streamlit", "run", "ui/app.py"]
