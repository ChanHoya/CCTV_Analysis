# Project State — CCTV Motion Analyzer

## Current Status
- **Frigate 방식 OpenCV 모션 감지 알고리즘 전환 완료 (S1-1)**:
  - 기존 DVR-Scan CLI 외부 프로세스 의존성을 완전히 제거하고, 순수 OpenCV `absdiff` 기반의 모션 감지 알고리즘을 성공적으로 구현 및 이식했습니다.
  - 연산 효율 최적화로 배치 분석 소요 시간이 6.9초에서 **2.9초**로 2배 이상 크게 개선되었습니다.
  - 리사이즈 폭(`frame_width`), 블러(`blur_radius`), 최소 면적(`min_area`), 정수형 임계값(`threshold`) 파라미터가 `config.yaml` 및 UI에 매끄럽게 연동되었습니다.
- **파이프라인 및 UI 동작 검증 완료**:
  - `tests/fixtures/` 샘플 비디오 5개에 대해 스모크 테스트가 5/5 성공적으로 완료되었습니다.
  - 튜닝 스크립트(`src/tune.py`)가 정상 리팩토링되어 임계값 면적 스윕을 성공적으로 출력합니다.
  - Streamlit UI(`ui/app.py`) 내 슬라이더 제어기가 새로운 Frigate 모션 감지 매개변수에 맞춰 갱신되었습니다.

## Next Steps / Active Sprint
- **Phase 7 (알림 기능, M3)**:
  - `src/notify.py` 구현 착수: 탐지 이벤트 JSON을 n8n 웹훅으로 POST 전송
  - 중복 알림을 막기 위한 동일 비디오 쿨다운 관리 및 UI 토글 연동
- **Phase 8 (추가 확장 옵션, M4)**:
  - (옵션) ByteTrack 등을 통한 객체 동선 및 체류 시간 추적 기능
  - (옵션) 원격 저장소 백업 연동 (개인정보 리스크 검토 후 설계)
