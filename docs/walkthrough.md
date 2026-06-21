# Walkthrough — Frigate 방식 OpenCV 모션 감지 이식 및 UI 개선 완료

기존 외부 DVR-Scan CLI의 프로세스 호출과 MOG2 오탐 문제를 해결하기 위해, Frigate 방식의 OpenCV absdiff 모션 스캔 알고리즘을 이식하고 UI 렌더링 결함을 전면 개선했습니다.

## 변경 사항 (Changes Made)

1. **설정 파일 업데이트**:
   - [config.yaml](file:///Users/chanhojung/Downloads/CCTV_Analysis/config.yaml): 기존 DVR-Scan 전용 필드를 제거하고, Frigate 알고리즘에 필요한 `frame_width`, `blur_radius`, `threshold`, `dilate_iterations`, `min_area` 파라미터를 추가했습니다.
   - [src/config.py](file:///Users/chanhojung/Downloads/CCTV_Analysis/src/config.py): 변경된 YAML 스키마에 따라 `MotionConfig` dataclass와 스키마 파서 로직을 갱신했습니다.
2. **모션 스캐너 전면 개편**:
   - [src/motion.py](file:///Users/chanhojung/Downloads/CCTV_Analysis/src/motion.py): 외부 서브프로세스 `dvr-scan` 호출을 완전히 제거하고, 순수 OpenCV(absdiff, GaussianBlur, Threshold, Dilate, Contours)로 동작하는 고속 모션 스캔 알고리즘 `scan_motion`을 구현했습니다.
3. **튜닝 스크립트 리팩토링**:
   - [src/tune.py](file:///Users/chanhojung/Downloads/CCTV_Analysis/src/tune.py): `dvr-scan` CLI 대신 OpenCV `scan_motion`을 사용해 고속으로 모션 감도 스윕을 수행하도록 개편하고, 0~255 정수형 임계값 범위를 테스트하도록 수정했습니다.
4. **UI 파라미터 연동 및 그리드 개선**:
   - [ui/app.py](file:///Users/chanhojung/Downloads/CCTV_Analysis/ui/app.py): 
     - **썸네일 유실 버그 수정**: SQLite Row 객체의 타입 판정 문제(`isinstance(ev, dict)`)로 인해 썸네일 경로가 누락되던 버그를 `dict(ev)` 변환 기법을 사용해 정상화했습니다. 이제 모션 클립 카드에 영상 스틸컷이 온전히 표시됩니다.
     - **컬럼 고정 그리드 도입**: 한 행에 7개의 모션 카드를 배치(`THUMB_COLS = 7`)하고 컬럼 크기를 고정하여, 마지막 줄에 잔여 카드가 있을 때 가로폭이 화면 절반을 덮던 그리드 레이아웃 오작동을 해결했습니다.
     - **종횡비 매핑**: 썸네일 미생성 시의 대체 아이콘 상자에 실제 비디오 해상도 가로/세로 비율(`aspect-ratio: vw/vh`)을 적용하여 왜곡 현상을 완벽히 차단했습니다.

---

## 검증 결과 (Validation Results)

### 1. 배치 파이프라인 통합 테스트
`tests/fixtures/` 내 5개 샘플 비디오에 대해 배치 분석 파이프라인(`src.pipeline`)을 실행했습니다.
- **성공률**: 5/5 성공
- **총 소요시간**: **2.9초** (기존 DVR-Scan 서브프로세스 기동 방식의 6.9초 대비 **2배 이상 속도 향상**)
- **동작 양상**:
  - `sample_static.mp4` 및 `sample_person.mp4` (움직임 없음): 모션 0건으로 정상 스킵
  - `sample_person_motion.mp4` (움직임 있음): 모션 구간이 감지되어 YOLO11 정밀 추론 단계로 매끄럽게 연결되며 8건의 유의미한 움직임 객체 최종 탐지 성공

### 2. 튜닝 스윕 도구 검증
- `tests/fixtures/sample_motion.mp4`에 대해 `python -m src.tune`을 실행하여 임계값 `[5, 10, 15, 20, 25, 30, 40, 50, 70]`의 모션 면적 스윕을 수행한 결과, 예외 없이 초당 분석 정보가 완벽히 스 Sweep되어 출력됨을 검증했습니다.
