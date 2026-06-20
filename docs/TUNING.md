# TUNING.md — 환경별 모션/탐지 파라미터 기록

> 실제 CCTV 영상으로 튜닝한 값을 환경(카메라 위치/화각/주야간)별로 기록한다.
> 측정: `python -m src.tune <video> [t1 t2 ...]` (scan-only, 클립 미기록)

## 튜닝 절차
1. 대표 영상(움직임 有/無 구간 포함)을 `tests/fixtures/`에 둔다.
2. `python -m src.tune <video>` 로 threshold 스윕 → 과탐/미탐 사이 안정 구간 선택.
3. 야외·노이즈가 많으면 `motion.kernel_size`(노이즈 커널), `motion.min_event_length`(짧은 깜빡임 무시)를 올린다.
4. 고해상도/대용량이면 `motion.downscale_factor`(2~4)로 속도·메모리 절감.
5. 빠른 처리가 필요하면 `motion.bg_subtractor: CNT`.
6. 선택한 값을 `config.yaml`에 반영하고 아래 표에 기록한다.

## 오탐 억제 가이드 (야외 비/그림자/흔들림)
| 증상 | 조정 |
|---|---|
| 작은 노이즈/벌레/빗방울 다수 검출 | `kernel_size` ↑ (예: 5,7), `min_event_length` ↑ |
| 나뭇잎/그림자 흔들림 | `regions`로 ROI 제한(관심 영역만), `threshold` ↑ |
| 카메라 흔들림 | `threshold` ↑, `downscale_factor` ↑ |
| 너무 둔감(놓침) | `threshold` ↓, `kernel_size` ↓ |

## 환경별 기록 표 (예시 — 실제 영상으로 채우기)
| 환경/카메라 | 해상도 | threshold | kernel_size | min_event_length | downscale | bg | sample_fps | conf | 비고 |
|---|---|---|---|---|---|---|---|---|---|
| (예) 주차장 주간 | 1920x1080 | 0.15 | -1 | 0.3s | 2 | MOG2 | 1.0 | 0.4 | 차량+사람 |
| (예) 현관 야간 | 1280x720 | 0.10 | 5 | 0.5s | 0 | MOG2 | 2.0 | 0.35 | 적외선, 노이즈↑ |
|  |  |  |  |  |  |  |  |  |  |

> ⚠️ 합성 픽스처(testsrc)는 모션이 균일해 모든 threshold에서 동일 결과가 나온다.
> 의미 있는 튜닝값은 **실제 영상**에서만 얻을 수 있다.
