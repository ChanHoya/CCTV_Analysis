# CCTV 모션 분석 시스템

다운로드한 CCTV 영상에서 **① 움직임 구간만 발췌 → ② 그 구간만 객체 탐지(사람/차량) → ③ 이벤트 기록·시각화**하는 로컬 우선(local-first) 분석 도구.

핵심은 **2단계 캐스케이드**: 값싼 모션 필터(DVR-Scan)로 입력을 걸러낸 뒤, 비싼 객체탐지(YOLO)를 모션 구간에만 적용한다.

```
업로드/정규화 → [DVR-Scan 모션 추출] → [YOLO 객체 분석] → SQLite 이벤트 + 썸네일 → 웹 UI
```

> ⚠️ 개인정보: CCTV 원본은 얼굴·차량번호를 포함한다. 본 시스템은 **원본/클립/썸네일을 `data/` 밖으로 내보내지 않는다.** 자세한 규칙은 `AGENTS.md` 참조.

---

## 빠른 시작

### 1) 설치
```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
# 시스템 의존성: ffmpeg, ffprobe (PATH에 있어야 함)
```

### 2) CLI 배치 분석
```bash
.venv/bin/python -m src.pipeline <영상폴더 또는 파일>
# 예: .venv/bin/python -m src.pipeline tests/fixtures
```
→ `data/clips/`(모션 클립), `data/thumbs/`(썸네일), `data/db/events.db`(이벤트) 생성.

### 3) 웹 UI (로컬/LAN)
```bash
./run_web.sh                 # → http://localhost:8501
```
업로드 또는 폴더 지정 → 분석 실행 → 이벤트/썸네일/클립/탐지 확인.
사이드바에서 threshold·sample_fps·conf를 조정할 수 있다.

### 4) 웹 UI (Docker 자체 호스팅)
```bash
docker compose up -d --build   # → http://localhost:8501
```
`data/`·`models/`는 호스트 볼륨에 영속된다(영상은 컨테이너 밖에 보관).

---

## 설정 (`config.yaml`)
모든 튜닝 값은 `config.yaml`에서만 읽는다(코드 하드코딩 없음).

| 키 | 의미 |
|---|---|
| `motion.threshold` | 모션 민감도(낮을수록 민감) |
| `motion.kernel_size` | 노이즈 제거 커널(야외 오탐 억제, -1=자동) |
| `motion.min_event_length` | 최소 이벤트 길이(짧은 깜빡임 무시) |
| `motion.downscale_factor` | 처리 전 다운스케일(대용량 속도/메모리) |
| `motion.bg_subtractor` | 배경차분 `MOG2`/`CNT` |
| `motion.regions` | ROI 다각형(관심 영역만 감지) |
| `detect.model` | YOLO 가중치(기본 `yolo11n.pt`) |
| `detect.sample_fps` | 클립 샘플링 fps(1~2 권장) |
| `detect.classes` | COCO 클래스(0=사람, 2/3/5/7=차량 등) |
| `detect.conf` | 탐지 신뢰도 임계값 |
| `detect.device` | `auto`/`cpu`/`cuda`/`mps` |
| `ingest.cleanup_normalized` | 정규화 임시파일 자동 삭제 |

### 환경별 튜닝
```bash
.venv/bin/python -m src.tune <영상> [t1 t2 ...]   # threshold 스윕(scan-only)
```
선택한 값은 `config.yaml`에 반영하고 `docs/TUNING.md`에 기록한다.

---

## 구조
```
src/
├─ config.py    # config.yaml 로더(스키마 검증)
├─ ingest.py    # ffprobe 검사 + 비표준→MP4 정규화
├─ motion.py    # DVR-Scan 모션 추출 → 클립/썸네일
├─ detect.py    # YOLO 객체 탐지(ultralytics 의존 격리)
├─ store.py     # SQLite(videos/motion_events/detections)
├─ pipeline.py  # ingest→motion→detect→store 오케스트레이션
└─ tune.py      # threshold 스윕 튜닝
ui/app.py       # Streamlit 웹 UI
data/           # 원본/클립/썸네일/DB (gitignore, 외부전송 금지)
models/         # YOLO 가중치 캐시
```

## 라이선스 주의
- DVR-Scan: BSD-2-Clause (상업적 자유)
- Ultralytics YOLO: **AGPL-3.0** — 상업 배포 시 검토 필수. 의존부는 `detect.py`에 격리되어 교체 가능.

## 미구현 (선택)
- Phase 7 알림(n8n 웹훅) — 보류
- ByteTrack 추적 / VLM 자연어 검색 — 미착수
- S3/GCS 연동 — 외부전송 개인정보 검토 후
