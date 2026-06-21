# Feature Registry — CCTV Motion Analyzer

| Feature ID | Feature Name | Description | Status | Target Module |
|---|---|---|---|---|
| F-001 | Ingest & Norm | ffprobe를 활용한 코덱/메타 검출 및 비표준 영상 FFmpeg 정규화 | 🟢 완료 | `src/ingest.py` |
| F-002 | Motion Scan | DVR-Scan CLI 연동 및 `--scan-only`를 이용한 고속 모션 세그먼트 추출 | 🟢 완료 | `src/motion.py` |
| F-003 | Cascade Detection | YOLO 객체 탐지 및 OpenCV MOG2 배경 차분 결합 (정지한 차량/사람 오탐 차단) | 🟢 완료 | `src/detect.py` |
| F-004 | Persistent Store | SQLite 기반 이벤트 저장, SHA256 멱등성 보장 및 Cascade Delete 처리 | 🟢 완료 | `src/store.py` |
| F-005 | Streamlit Dashboard | 분석 모니터링, 이벤트 썸네일 탐색, 클립별 비디오 직접 재생 및 슬라이더 튜닝 | 🟢 완료 | `ui/app.py` |
| F-006 | CLI Tuning sweeps | 영상 분석 전 모션 감지 임계값 최적화를 위한 스윕 CLI 제공 | 🟢 완료 | `src/tune.py` |
| F-007 | Event Notification | n8n 웹훅을 통한 텔레그램/이메일 알림 및 동일 영상 쿨다운 제어 | 🔴 대기 | `src/notify.py` |
| F-008 | Object Tracking | ByteTrack 등을 통한 객체 고유 ID 부여 및 체류 시간/동선 추적 | 🔴 대기 (옵션) | TBD |
| F-009 | Remote Cloud Backup | 분석 완료 영상 및 썸네일을 S3/GCS/MinIO 등 원격 저장소에 아카이빙 | 🔴 대기 (옵션) | TBD |
