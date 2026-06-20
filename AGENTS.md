# AGENTS.md — CCTV 모션 추출·분석 시스템

> 이 파일은 Antigravity(및 호환 에이전트)가 본 저장소에서 작업할 때 **반드시 지켜야 할 규칙**이다.
> 코드를 생성/수정하기 전에 이 문서를 먼저 읽고, 충돌 시 이 문서를 우선한다.

---

## 0. 프로젝트 한 줄 정의
CCTV 시스템에서 **다운로드한 영상 파일**을 입력받아, **① 움직임(모션) 구간만 발췌**하고 **② 그 구간만 객체 탐지(사람/차량)** 한 뒤 **③ 이벤트로 기록·시각화**하는 로컬 우선(local-first) 분석 시스템.

핵심 설계 = **2단계 캐스케이드**: 값싼 모션 필터로 입력을 99% 이상 걸러낸 뒤, 비싼 객체탐지를 모션 구간에만 적용한다.

```
업로드/정규화 → [DVR-Scan 모션 추출] → [YOLO 객체 분석] → 이벤트 DB/시각화/(선택)알림
```

---

## 1. 절대 규칙 (HARD CONSTRAINTS — 위반 금지)

1. **CCTV 원본 영상을 외부로 업로드하지 않는다.**
   - YouTube(비공개/일부공개 포함), 외부 클라우드 분석 API, 기타 제3자 서비스로 **원본/식별가능 영상을 전송 금지**.
   - 이유: CCTV 영상은 개인정보(얼굴·차량번호)를 포함하며 개인정보보호법 리스크가 크다.
   - 외부 전송이 꼭 필요한 기능을 구현해야 하면, **코드로 바로 만들지 말고 사람에게 먼저 확인**한다.

2. **라이브러리 API를 추측하지 않는다.**
   - 확실하지 않은 함수 시그니처/플래그/가중치 파일명은 **공식 문서를 확인**하거나, 확인 전에는 TODO로 남기고 사람에게 묻는다.
   - 특히 **DVR-Scan은 검증된 CLI 플래그**(아래 5장)로 호출한다. Python 내부 API는 문서 확인 후에만 사용.
   - **YOLO26 가중치 파일명은 단정 금지** — 확실히 존재하는 `yolo11n.pt`를 기본값으로 쓰고, YOLO26 사용 시 Ultralytics 문서에서 정확한 이름을 확인한다.

3. **매직 넘버 금지.** 모든 튜닝 값(임계값, 샘플 fps, ROI, 모델명, 클래스 목록, 알림 설정)은 `config.yaml`에서만 읽는다. 코드에 하드코딩 금지.

4. **단계별 샘플 검증.** 각 모듈은 **짧은 샘플 영상 1개**로 동작을 통과시킨 뒤 다음 단계로 넘어간다. 전체 파이프라인을 한 번에 만들고 끝에서 검증하지 않는다.

5. **시크릿 하드코딩 금지.** 텔레그램 토큰·웹훅 URL 등은 `.env`/환경변수로만. `.env`는 `.gitignore`에 포함.

6. **사실 기반·환각 금지.** 모르는 것은 "모른다/확인 필요"로 명시. 추측성 구현이나 거짓 주석을 넣지 않는다. 오류를 지적받으면 즉시 인정하고 같은 실수를 반복하지 않는다.

---

## 2. 하지 말아야 할 안티패턴 (DON'T)

- ❌ YouTube를 저장소/트랜스코딩 백엔드로 사용 → 화질 저하·취약·개인정보 리스크.
- ❌ `yt-dlp`로 스트림 URL 뽑아 분석하는 파이프라인 구축.
- ❌ FFmpeg `select='gt(scene,...)'`(장면 전환 감지)를 "모션 감지"로 사용 → 고정 CCTV 화면에 부정확. 모션은 **배경차분(DVR-Scan/OpenCV MOG2)** 으로.
- ❌ 모든 프레임을 YOLO에 투입 → 연산 낭비. **1~2 fps 샘플링**.
- ❌ 임계값/경로 하드코딩.
- ❌ 검증 없이 "동작할 것"이라고 가정한 코드 작성.

---

## 3. 기술 스택 (확정)

| 영역 | 선택 | 라이선스/비고 |
|---|---|---|
| 언어 | Python 3.11+ | |
| 모션 추출 | **DVR-Scan** (`pip install "dvr-scan[opencv]"`, 서버는 `dvr-scan-headless`) | **BSD-2-Clause**(상업적 자유) |
| 객체 탐지 | **Ultralytics YOLO11**(기본) / YOLO26(옵션) | **AGPL-3.0** 또는 상용 — 상업 배포 시 검토 필수 |
| 영상 처리 | OpenCV, FFmpeg(`ffprobe` 포함) | |
| 저장 | SQLite(MVP) → PostgreSQL(확장) | 영상은 로컬 `data/`; 필요 시 S3/GCS/MinIO |
| UI | Streamlit 또는 Gradio(빠른 로컬 UI) | 웹 확장 시 Next.js 검토 |
| 알림(선택) | n8n 웹훅 → 텔레그램/이메일 | 토큰은 `.env` |

> 라이선스 주의: DVR-Scan(BSD)과 YOLO(AGPL)는 라이선스가 다르다. YOLO 의존부는 `detect.py`로 격리해 교체 가능하게 둔다.

---

## 4. 디렉터리 구조 (이 구조를 유지/생성)

```
cctv-motion-analyzer/
├─ AGENTS.md            # 본 규칙 파일
├─ TASKS.md             # 태스크 체크리스트
├─ pyproject.toml
├─ config.yaml          # 모든 튜닝 파라미터
├─ .env.example         # 시크릿 템플릿(실제 .env는 커밋 금지)
├─ src/
│  ├─ ingest.py         # 업로드/정규화/ffprobe 검사
│  ├─ motion.py         # DVR-Scan 호출 → 모션 구간/클립/썸네일
│  ├─ detect.py         # YOLO로 클립 분석 → 이벤트(여기에만 ultralytics 의존)
│  ├─ store.py          # DB(SQLite) 입출력
│  ├─ notify.py         # n8n/텔레그램(선택)
│  ├─ pipeline.py       # ①~④ 오케스트레이션 + 진행률 로깅
│  └─ config.py         # config.yaml 로더(스키마 검증)
├─ ui/                  # Streamlit/Gradio 앱
├─ tests/               # 샘플 영상 기반 스모크 테스트
└─ data/
   ├─ uploads/          # 원본
   ├─ clips/            # 모션 클립
   ├─ thumbs/           # 썸네일
   └─ db/               # sqlite 파일
```

---

## 5. 검증된 외부 명령 (그대로 사용)

**DVR-Scan (CLI, ffmpeg 무손실 copy 모드 + 대표 썸네일):**
```bash
dvr-scan -i <입력영상> -o <출력폴더> -m ffmpeg -t <threshold> --thumbnails highscore
# ROI 지정: -r (GUI 에디터) 또는 -a x y x y ...(좌표 다각형)
# 야외 오탐 억제 옵션(min-event-length, max-area 등)은 문서 확인 후 config로 노출
```
- `-t/--threshold`: 낮을수록 민감(작은 움직임도 감지). 실제 영상으로 튜닝.
- `-m ffmpeg`: 재인코딩 없이 잘라 화질 보존 + 속도↑.

**FFmpeg/ffprobe (정규화·검사):**
```bash
ffprobe -v error -show_entries format=duration:stream=codec_name,width,height,r_frame_rate -of json <입력영상>
ffmpeg -i <입력> -c:v libx264 -an <표준화.mp4>   # 비표준 컨테이너만 정규화
```

**YOLO (Python, 사람=COCO class 0):**
```python
from ultralytics import YOLO
model = YOLO("yolo11n.pt")            # YOLO26은 가중치명 문서 확인
r = model(frame, classes=[0], verbose=False)[0]
```

---

## 6. 코딩 컨벤션

- 타입 힌트 필수. 함수는 단일 책임, 부수효과 최소화.
- 표준 `logging` 사용(진행률·이벤트 수·소요시간 기록). `print` 디버깅 잔재 금지.
- 외부 명령은 `subprocess.run(..., check=True)`로 호출하고 실패를 명확히 전파.
- 모든 경로는 `pathlib.Path`. 절대경로 하드코딩 금지(config 기준 상대경로).
- 예외 처리: 손상 영상·빈 모션 결과·GPU 미가용을 graceful하게 처리(빈 결과 반환 + 경고 로그).
- 한 PR/커밋 = 한 모듈/한 태스크. TASKS.md의 항목과 1:1 매핑.

---

## 7. 데이터·개인정보 취급 규칙

- 원본·클립·썸네일은 `data/` 밖으로 나가지 않는다.
- 로그·이벤트 JSON에 영상 프레임(픽셀)을 인라인으로 담지 않는다(경로만 기록).
- (선택) 분석에 불필요한 얼굴/번호판 블러 기능을 둘 경우, **저장 전에** 적용하는 옵션으로 설계.
- 보관기간·접근권한 등 구체 의무는 사안별로 다르므로, 정책 수치는 사람이 PIPC 등 공식 출처로 확정한 뒤 config에 반영(에이전트가 임의 가정 금지).

---

## 8. 모듈별 완료 정의 (Definition of Done)

- **ingest**: 샘플 영상의 길이/fps/해상도/코덱을 정확히 출력하고, 비표준 포맷을 표준 MP4로 변환한다.
- **motion**: 샘플 영상에서 모션 구간 수와 각 클립/썸네일 파일을 생성한다. 모션이 없으면 빈 목록을 반환(에러 아님).
- **detect**: 모션 클립 1개에서 1fps 샘플링으로 사람 탐지 이벤트(클립경로·시각·개수)를 반환한다.
- **store**: 이벤트가 SQLite에 저장되고 재조회된다.
- **pipeline**: 폴더의 영상 N개를 받아 end-to-end로 이벤트 테이블과 썸네일을 생성하며 진행률을 로깅한다.
- **ui/notify(선택)**: 타임라인·썸네일 확인 / 이벤트 발생 시 알림 1건 전송.

---

## 9. 작업 절차 (에이전트 루프)

1. `TASKS.md`에서 미완료(`[ ]`) 항목 **하나**를 고른다.
2. 이 문서의 규칙을 위반하지 않는지 확인한다.
3. 구현 → 샘플로 검증 → 통과 시 `TASKS.md` 해당 항목을 `[x]`로 갱신.
4. 불확실하거나 외부 전송/라이선스/개인정보가 얽히면 **멈추고 사람에게 질문**한다.
