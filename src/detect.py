"""Detect — 원본 영상 구간을 샘플링해 YOLO로 객체 탐지.

핵심 로직: 배경 차분(MOG2) 마스크와 YOLO 바운딩 박스를 결합하여
실제로 움직이는 객체만 탐지 — 정지한 배경 인물/차량은 제외.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import cv2

from src.config import Config

logger = logging.getLogger(__name__)

MOTION_RATIO_MIN = 0.04   # bbox 픽셀 중 최소 4%가 전경(움직임) 픽셀이어야 탐지 인정
WARMUP_SEC = 4.0           # 이벤트 시작 전 배경 모델 워밍업 시간(초)


@dataclass(frozen=True)
class DetectionEvent:
    clip_path: Path     # 실제로는 원본 영상 경로
    t_sec: float        # 이벤트 내 상대 시각
    class_id: int
    class_name: str
    n: int
    conf: float


def _resolve_device(device: str) -> str:
    import torch
    if device != "auto":
        return device
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    logger.warning("GPU(cuda/mps) 미가용 → CPU fallback")
    return "cpu"


@lru_cache(maxsize=4)
def _load_model(model_path: str):
    from ultralytics import YOLO
    return YOLO(model_path)


def _model_for(cfg: Config):
    cfg.paths.models.mkdir(parents=True, exist_ok=True)
    weights = cfg.paths.models / cfg.detect.model
    return _load_model(str(weights))


def _agg_from_result_motion_filtered(
    result,
    fg_mask,
    video_path: Path,
    t_sec: float,
    names: dict,
) -> list[DetectionEvent]:
    """YOLO 결과에서 움직임 마스크와 겹치는 박스만 집계."""
    boxes = result.boxes
    if boxes is None or len(boxes) == 0:
        return []

    h, w = fg_mask.shape[:2]
    agg: dict[int, tuple[int, float]] = {}

    for box, cls_id, conf in zip(
        boxes.xyxy.tolist(), boxes.cls.tolist(), boxes.conf.tolist()
    ):
        x1, y1, x2, y2 = int(box[0]), int(box[1]), int(box[2]), int(box[3])
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        if x2 <= x1 or y2 <= y1:
            continue

        roi = fg_mask[y1:y2, x1:x2]
        total_px = roi.size
        if total_px == 0:
            continue
        motion_ratio = cv2.countNonZero(roi) / total_px

        if motion_ratio < MOTION_RATIO_MIN:
            continue  # 정지 객체 → 제외

        cid = int(cls_id)
        n, cmax = agg.get(cid, (0, 0.0))
        agg[cid] = (n + 1, max(cmax, float(conf)))

    return [
        DetectionEvent(video_path, t_sec, cid, str(names.get(cid, cid)), n, round(cmax, 3))
        for cid, (n, cmax) in agg.items()
    ]


def detect_segment(
    video_path: Path,
    start_sec: float,
    end_sec: float,
    cfg: Config,
) -> list[DetectionEvent]:
    """원본 영상의 start_sec~end_sec 구간에서 YOLO 탐지.

    배경 차분 마스크(MOG2)를 함께 사용하여 정지 객체는 제외하고
    실제로 움직이는 객체만 반환한다.
    """
    video_path = Path(video_path)
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        logger.warning("영상 열기 실패: %s", video_path)
        return []

    video_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, round(video_fps / cfg.detect.sample_fps))
    start_frame = int(start_sec * video_fps)
    end_frame = int(end_sec * video_fps)

    # 배경 모델 워밍업: 이벤트 시작 전 WARMUP_SEC 초부터 처리
    warmup_start = max(0, start_frame - int(WARMUP_SEC * video_fps))
    cap.set(cv2.CAP_PROP_POS_FRAMES, warmup_start)

    bg_sub = cv2.createBackgroundSubtractorMOG2(
        history=max(50, start_frame - warmup_start),
        varThreshold=16,
        detectShadows=False,
    )

    model = _model_for(cfg)
    device = _resolve_device(cfg.detect.device)

    events: list[DetectionEvent] = []
    frame_idx = warmup_start

    while frame_idx <= end_frame:
        ok, frame = cap.read()
        if not ok:
            break

        fg_mask = bg_sub.apply(frame)

        if frame_idx >= start_frame and (frame_idx - start_frame) % step == 0:
            t_sec = (frame_idx - start_frame) / video_fps
            result = model.predict(
                frame, classes=cfg.detect.classes, conf=cfg.detect.conf,
                device=device, verbose=False,
            )[0]
            dets = _agg_from_result_motion_filtered(
                result, fg_mask, video_path, t_sec, model.names
            )
            events.extend(dets)

        frame_idx += 1

    cap.release()
    logger.info(
        "탐지 %d건 (움직임 필터 적용): %s [%.1f–%.1f]s",
        len(events), video_path.name, start_sec, end_sec,
    )
    return events


def detect_clip(clip_path: Path, cfg: Config) -> list[DetectionEvent]:
    """클립 파일을 샘플링해 탐지 (움직임 필터 없음). 레거시 호환용."""
    clip_path = Path(clip_path)
    cap = cv2.VideoCapture(str(clip_path))
    if not cap.isOpened():
        logger.warning("클립 열기 실패: %s", clip_path)
        return []

    video_fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    if video_fps <= 0:
        video_fps = 1.0
    step = max(1, round(video_fps / cfg.detect.sample_fps))

    model = _model_for(cfg)
    device = _resolve_device(cfg.detect.device)

    events: list[DetectionEvent] = []
    frame_idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if frame_idx % step == 0:
            t_sec = frame_idx / video_fps
            result = model.predict(
                frame, classes=cfg.detect.classes, conf=cfg.detect.conf,
                device=device, verbose=False,
            )[0]
            boxes = result.boxes
            if boxes and len(boxes):
                agg: dict[int, tuple[int, float]] = {}
                for cid, conf in zip(boxes.cls.tolist(), boxes.conf.tolist()):
                    n, cm = agg.get(int(cid), (0, 0.0))
                    agg[int(cid)] = (n + 1, max(cm, float(conf)))
                events.extend(
                    DetectionEvent(clip_path, t_sec, cid, str(model.names.get(cid, cid)), n, round(cm, 3))
                    for cid, (n, cm) in agg.items()
                )
        frame_idx += 1

    cap.release()
    return events
