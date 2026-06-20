# TASKS.md — 개발 태스크 체크리스트

> 규칙은 `AGENTS.md` 참조. 각 태스크는 **샘플 영상으로 검증**한 뒤 `[x]`로 표시한다.
> 한 번에 하나씩, 위에서부터. 외부 전송/라이선스/개인정보가 얽히면 멈추고 질문.

준비물: 짧은 테스트용 CCTV 클립 1~2개(`tests/fixtures/`에 배치). 움직임 있는 구간과 없는 구간이 모두 포함되면 좋음.

---

## Phase 0 — 프로젝트 셋업
- [x] 저장소 초기화, `pyproject.toml` 생성(Python 3.11+) — 기존 pension_plan repo 내 프로젝트 루트로 운용(중첩 git init 미수행)
- [x] `AGENTS.md`, `TASKS.md`를 루트에 배치
- [x] 디렉터리 구조 생성(`src/ ui/ tests/ data/{uploads,clips,thumbs,db}`)
- [x] 의존성 설치: `dvr-scan[opencv]`, `ultralytics`, `opencv-python`, `pyyaml`, `streamlit` (`.venv`)
- [x] 시스템 의존성 확인: `ffmpeg`, `ffprobe` 설치/PATH 확인 (8.0.1)
- [x] `config.yaml` + `src/config.py`(스키마 검증 로더) 작성 — 키: `paths`, `motion.*`, `detect.*`, `ingest.*`, `notify.*`
- [x] `.env.example` 작성, `.env`/`data/`/`models/`를 `.gitignore`에 추가
- [x] **검증**: `python -c "import cv2, ultralytics, yaml"` 및 `dvr-scan --version`, `ffmpeg -version` 정상 출력

## Phase 1 — Ingest (업로드/정규화/검사)
- [x] `ingest.py`: 입력 영상 경로 수집(폴더 스캔 또는 단일 파일)
- [x] `ffprobe`로 길이·fps·해상도·코덱·손상 여부 추출(JSON 파싱)
- [x] 비표준 컨테이너만 표준 MP4(H.264)로 정규화(이미 표준이면 스킵)
- [x] 손상/0바이트/디코딩 불가 파일은 경고 로그 후 건너뜀
- [x] **검증(DoD)**: 샘플 영상의 메타데이터를 정확히 출력하고, 비표준 샘플이 변환됨

## Phase 2 — Motion (DVR-Scan 모션 추출) ★핵심
- [x] `motion.py`: 검증된 CLI로 DVR-Scan 호출
      ⚠️ 1.8.2.1 `--help` 검증 결과 `-o`는 단일 .avi용 → 디렉터리 출력은 `-d` 사용
      `dvr-scan -i <in> -d <clips_dir> -m ffmpeg -t <t> -l <len> -tb <s> -tp <s> --thumbnails highscore -q`
- [x] 결과 클립 목록 + 대표 썸네일 경로 반환 (썸네일은 thumbs/로 이동, 이벤트 start/end 포함)
- [x] 모션 없음(빈 결과)을 정상 처리(에러 아님)
- [x] `threshold`, ROI(`-a` 다각형), `min_event_length`(`-l`), 전후 패딩(`-tb`/`-tp`)을 `config.yaml`로 노출
- [x] **검증(DoD)**: 움직임 구간 영상에서 1개 이상 클립/썸네일 생성, 정지 영상에서 0개 — 둘 다 정상 종료

## Phase 3 — Detect (YOLO 객체 분석)
- [x] `detect.py`: 모션 클립을 1~2 fps로 샘플링(`sample_fps`)
- [x] YOLO 로드(`yolo11n.pt` 기본; 가중치는 models/로 자동 다운로드, ultralytics 의존 격리)
- [x] 사람(class 0) 우선, 차량 등은 config 클래스 목록으로 확장
- [x] 탐지 이벤트 반환: `{clip, t_sec, class, n, conf}`
- [x] GPU 미가용 시 CPU로 fallback + 경고 로그 (auto→cuda/mps/cpu)
- [x] **검증(DoD)**: 사람이 등장하는 모션 클립에서 이벤트 1건 이상, 빈 클립에서 0건

## Phase 4 — Store (이벤트 저장)
- [x] `store.py`: SQLite 스키마(`videos`, `motion_events`, `detections`) 생성 (FK CASCADE)
- [x] 이벤트 insert/조회 함수, 원본↔클립↔탐지 관계 보존
- [x] 재실행 시 중복 처리 방지(SHA-256 UNIQUE 기준 idempotent, 재처리 시 결과 교체)
- [x] **검증(DoD)**: 이벤트가 저장되고 쿼리로 재조회됨

## Phase 5 — Pipeline (오케스트레이션)
- [x] `pipeline.py`: ingest → motion → detect → store 연결
- [x] 폴더 내 다중 파일 배치 처리
- [x] 진행률·소요시간·이벤트 수 로깅
- [x] 단계별 실패가 전체를 중단시키지 않도록 파일 단위 격리(한 파일 실패해도 다음 진행)
- [x] **검증(DoD)**: 영상 N개를 넣으면 end-to-end로 이벤트 테이블 + 썸네일이 생성됨

## Phase 6 — UI (확인용)
- [x] Streamlit: 파일 업로드 또는 폴더 지정 (`ui/app.py`)
- [x] 이벤트 목록 + 썸네일 그리드
- [x] 이벤트 선택 시 해당 모션 클립 재생 (st.video)
- [x] 임계값/fps/conf를 UI 슬라이더로 조정(→ dataclasses.replace로 config 반영)
- [x] **검증(DoD)**: 앱 정상 기동(HTTP 200) + 분석 결과 렌더 경로 확인 (`streamlit run ui/app.py`)

## Phase 7 — Notify (선택)
- [ ] `notify.py`: 이벤트 JSON을 n8n 웹훅으로 POST
- [ ] n8n에서 텔레그램/이메일 분기(토큰은 `.env`)
- [ ] 알림 빈도 제한(쿨다운)으로 스팸 방지
- **검증(DoD)**: 사람 탐지 시 알림 1건 수신, 쿨다운 동작

## Phase 8 — 튜닝·견고화 (선택/지속)
- [x] 실제 영상으로 `threshold`/ROI/`sample_fps` 튜닝 — `src/tune.py`(scan-only 스윕) + `docs/TUNING.md` 기록 템플릿
- [x] 야외 오탐(비·그림자·흔들림) 억제 옵션 적용 — `kernel_size`/`min_event_length`/`bg_subtractor`/ROI config 노출
- [x] 대용량 영상 메모리/디스크 — `downscale_factor`(-df), 프레임 스트리밍 처리, 정규화 임시파일 자동 정리(`cleanup_normalized`)
- [ ] (옵션) 추적(ByteTrack)으로 동선/체류시간, VLM 자연어 검색 확장 — 미착수
- [ ] (옵션) 저장이 필요하면 S3/GCS/MinIO 연동(원본 외부전송은 개인정보 검토 후) — 미착수(외부전송 검토 필요)

---

## 마일스톤
- **M1 (MVP)**: Phase 0~5 — 영상 넣으면 사람 탐지 이벤트가 DB/썸네일로 나옴
- **M2**: Phase 6 — 결과 확인 UI
- **M3**: Phase 7 — 알림
- **M4**: Phase 8 — 튜닝·확장

## 정의된 "완료"의 공통 기준
- 샘플 영상으로 재현 가능하게 검증됨
- 매직 넘버 없음(모두 config)
- 외부로 원본 영상 전송 없음
- 불확실 API는 문서 확인 완료(추측 흔적 없음)
