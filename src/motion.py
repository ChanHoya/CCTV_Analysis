"""Motion — OpenCV 기반 Frigate 스타일 모션 구간 타임스탬프 추출.

absdiff(이전 프레임과의 차분) + Gaussian Blur + 이진화 + 팽창(Dilate) + 윤곽선(Contours) 검출
기법을 사용하여 센서 노이즈 및 서서히 발생하는 조명 변화(드리프트) 오탐을 억제합니다.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from src.config import Config

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MotionClip:
    """모션 이벤트 메타. clip_path = 원본 영상 경로 (별도 클립 파일 없음)."""
    clip_path: Path
    thumbnail_path: Path | None
    start_sec: float
    end_sec: float


def _merge_close_events(
    events: list[tuple[float, float]], gap_sec: float
) -> list[tuple[float, float]]:
    """gap_sec 이내 간격의 연속 이벤트를 하나로 병합."""
    if not events or gap_sec <= 0:
        return events
    sorted_ev = sorted(events, key=lambda e: e[0])
    merged = [sorted_ev[0]]
    for s, e in sorted_ev[1:]:
        ps, pe = merged[-1]
        if s - pe < gap_sec:
            merged[-1] = (ps, max(pe, e))
        else:
            merged.append((s, e))
    return merged


def _parse_min_event_len_frames(val: str, fps: float) -> int:
    """min_event_length 값("1s" 또는 정수 프레임)을 프레임 수로 변환."""
    if isinstance(val, str) and val.endswith("s"):
        try:
            return max(1, int(float(val[:-1]) * fps))
        except ValueError:
            return 1
    return max(1, int(val))


def _extract_events_from_frames(
    motion_detected: list[bool],
    fps: float,
    min_event_len_frames: int,
    time_before_event: float,
    time_post_event: float,
    total_frames: int,
) -> list[tuple[float, float]]:
    """프레임별 모션 감지 플래그 목록으로부터 이벤트 타임스탬프를 묶어 반환."""
    events: list[tuple[float, float]] = []
    in_event = False
    event_start_frame = -1
    last_motion_frame = -1

    post_event_frames = int(time_post_event * fps)
    before_event_frames = int(time_before_event * fps)

    for i, detected in enumerate(motion_detected):
        if detected:
            if not in_event:
                in_event = True
                event_start_frame = i
            last_motion_frame = i
        else:
            if in_event:
                # 마지막 모션 감지 프레임 이후 post_event_frames 만큼 무동작 지속 시 이벤트 종료
                if i - last_motion_frame >= post_event_frames:
                    duration_frames = last_motion_frame - event_start_frame + 1
                    if duration_frames >= min_event_len_frames:
                        s_idx = max(0, event_start_frame - before_event_frames)
                        e_idx = min(total_frames - 1, last_motion_frame + post_event_frames)
                        events.append((s_idx / fps, e_idx / fps))
                    in_event = False

    # 영상 종료 시 닫히지 않은 이벤트 처리
    if in_event:
        duration_frames = last_motion_frame - event_start_frame + 1
        if duration_frames >= min_event_len_frames:
            s_idx = max(0, event_start_frame - before_event_frames)
            e_idx = min(total_frames - 1, last_motion_frame + post_event_frames)
            events.append((s_idx / fps, e_idx / fps))

    return events


def scan_motion(
    video_path: Path,
    cfg: Config,
    progress_cb: Callable[[float, str], None] | None = None,
    video_duration: float = 0.0,
) -> list[tuple[float, float]]:
    """OpenCV absdiff 기반 모션 세그먼트 스캐너.

    Returns:
        [(start_sec, end_sec), ...]  모션 없으면 빈 리스트.
    """
    video_path = Path(video_path)
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        logger.warning("모션 분석 영상을 열 수 없음: %s", video_path)
        return []

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    # 파라미터 캐싱
    frame_width = cfg.motion.frame_width
    blur_radius = cfg.motion.blur_radius
    if blur_radius % 2 == 0:
        blur_radius += 1  # Gaussian Blur 커널은 반드시 홀수여야 함
    threshold_val = cfg.motion.threshold
    dilate_iter = cfg.motion.dilate_iterations
    min_area = cfg.motion.min_area

    # 리사이즈 해상도 연산
    rw, rh = w, h
    if frame_width > 0 and w > frame_width:
        aspect = h / w
        rw = frame_width
        rh = int(frame_width * aspect)

    # ROI 마스크 빌드
    roi_mask = np.ones((rh, rw), dtype=np.uint8) * 255
    if cfg.motion.regions:
        roi_mask = np.zeros((rh, rw), dtype=np.uint8)
        for poly in cfg.motion.regions:
            pts = np.array(poly, dtype=np.int32).reshape((-1, 2))
            pts[:, 0] = (pts[:, 0] * (rw / w)).astype(np.int32)
            pts[:, 1] = (pts[:, 1] * (rh / h)).astype(np.int32)
            cv2.fillPoly(roi_mask, [pts], 255)

    logger.info(
        "모션 감지 시작: %s (resize=%dx%d, threshold=%d, min_area=%d)",
        video_path.name, rw, rh, threshold_val, min_area,
    )

    prev_frame = None
    motion_detected: list[bool] = []

    frame_idx = 0
    cb_step = max(1, total_frames // 20)  # 5% 진행 마다 로그/콜백 업데이트

    while True:
        ok, frame = cap.read()
        if not ok:
            break

        # resize
        if frame_width > 0 and w > frame_width:
            frame_resized = cv2.resize(frame, (rw, rh))
        else:
            frame_resized = frame

        # gray & blur
        gray = cv2.cvtColor(frame_resized, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (blur_radius, blur_radius), 0)

        if prev_frame is None:
            prev_frame = gray
            motion_detected.append(False)
            frame_idx += 1
            continue

        # absdiff
        diff = cv2.absdiff(prev_frame, gray)
        _, thresh = cv2.threshold(diff, threshold_val, 255, cv2.THRESH_BINARY)
        dilated = cv2.dilate(thresh, None, iterations=dilate_iter)

        # ROI 적용
        if cfg.motion.regions:
            dilated = cv2.bitwise_and(dilated, roi_mask)

        # contours & area filter
        contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        has_motion = any(cv2.contourArea(c) > min_area for c in contours)

        motion_detected.append(has_motion)
        prev_frame = gray

        frame_idx += 1
        if progress_cb and frame_idx % cb_step == 0 and total_frames > 0:
            p = min(0.95, frame_idx / total_frames)
            progress_cb(p, f"모션 감지 분석 중… ({frame_idx}/{total_frames} 프레임)")

    cap.release()

    if progress_cb:
        progress_cb(1.0, "모션 분석 완료")

    # 프레임 감지 이력을 바탕으로 세그먼트 생성
    events = _extract_events_from_frames(
        motion_detected,
        fps,
        _parse_min_event_len_frames(cfg.motion.min_event_length, fps),
        cfg.motion.time_before_event,
        cfg.motion.time_post_event,
        total_frames,
    )

    merged = _merge_close_events(events, cfg.motion.merge_gap_sec)
    logger.info("모션 이벤트 %d건 (병합 후 %d건): %s", len(events), len(merged), video_path.name)
    return merged


if __name__ == "__main__":
    import sys

    from src.config import ensure_dirs, load_config, setup_logging

    cfg = load_config()
    setup_logging(cfg.logging_level)
    ensure_dirs(cfg)

    target = sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures/sample_motion.mp4"
    for s, e in scan_motion(Path(target), cfg):
        print(f"  [{s:.1f}s – {e:.1f}s]  ({e - s:.1f}s)")
