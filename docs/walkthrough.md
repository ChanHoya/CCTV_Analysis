# Walkthrough — Frigate 방식 OpenCV 모션 감지 이식 및 UI 개선 완료

기존 외부 DVR-Scan CLI의 프로세스 호출과 MOG2 오탐 문제를 해결하기 위해, Frigate 방식의 OpenCV absdiff 모션 스캔 알고리즘을 이식하고 UI 렌더링 및 썸네일 추출 방식을 고도화했습니다.

## 변경 사항 (Changes Made)

1. **설정 파일 업데이트**:
   - [config.yaml](file:///Users/chanhojung/Downloads/CCTV_Analysis/config.yaml): 기존 DVR-Scan 전용 필드를 제거하고, Frigate 알고리즘에 필요한 `frame_width`, `blur_radius`, `threshold`, `dilate_iterations`, `min_area` 파라미터를 추가했습니다.
   - [src/config.py](file:///Users/chanhojung/Downloads/CCTV_Analysis/src/config.py): 변경된 YAML 스키마에 따라 `MotionConfig` dataclass와 스키마 파서 로직을 갱신했습니다.
2. **모션 스캐너 전면 개편**:
   - [src/motion.py](file:///Users/chanhojung/Downloads/CCTV_Analysis/src/motion.py): 외부 서브프로세스 `dvr-scan` 호출을 완전히 제거하고, 순수 OpenCV(absdiff, GaussianBlur, Threshold, Dilate, Contours)로 동작하는 고속 모션 스캔 알고리즘 `scan_motion`을 구현했습니다.
3. **대표 썸네일 알고리즘 탑재**:
   - [src/pipeline.py](file:///Users/chanhojung/Downloads/CCTV_Analysis/src/pipeline.py): 단순 중간지점을 썸네일로 캡처하던 기존 방식 대신, 모션 구간 내에서 **YOLO가 탐지한 객체 수의 합이 가장 많고 탐지 신뢰도가 가장 높은 최적의 프레임 시점**을 판별하여 대표 썸네일 이미지로 추출하도록 구현했습니다. 객체 탐지가 0건인 구간은 중간 시점으로 안전하게 폴백합니다.
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
- **대표 썸네일 선정 검증**:
  - `sample_person_motion.mp4` 분석 시, 기존 2.0s 중간 시점 대신 **사람이 3명 등장하고 신뢰도 0.866으로 가장 잘 나오는 시점인 1.00s 프레임**을 성공적으로 계산 및 타겟 썸네일 이미지로 추출 완료했습니다.
  - 로그: `INFO [__main__] 대표 썸네일 선정: 1.00s (상대 1.00s, 객체수=3, conf=0.866)`

### 2. 튜닝 스윕 도구 검증
- `tests/fixtures/sample_motion.mp4`에 대해 `python -m src.tune`을 실행하여 임계값 `[5, 10, 15, 20, 25, 30, 40, 50, 70]`의 모션 면적 스윕을 수행한 결과, 예외 없이 초당 분석 정보가 완벽히 스 Sweep되어 출력됨을 검증했습니다.
