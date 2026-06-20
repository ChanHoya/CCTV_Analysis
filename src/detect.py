"""Detect — 모션 클립을 샘플링해 YOLO로 객체 탐지(사람/차량 등).

AGENTS.md §3: ultralytics 의존은 이 모듈에만 격리(라이선스 분리, 교체 용이).
AGENTS.md §1.2: 가중치는 확실히 존재하는 `yolo11n.pt` 기본. 클래스 0=사람(COCO).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import cv2

from src.config import Config

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DetectionEvent:
    clip_path: Path
    t_sec: float       # 클립 내 시각
    class_id: int
    class_name: str
    n: int             # 해당 프레임에서 그 클래스 탐지 개수
    conf: float        # 그 클래스 최대 신뢰도


def _resolve_device(device: str) -> str:
    """config의 device를 실제 사용 가능한 장치로 해석. GPU 미가용 시 cpu fallback."""
    import torch

    if device != "auto":
        return device
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    logger.warning("GPU(cuda/mps) 미가용 → CPU로 fallback")
    return "cpu"


@lru_cache(maxsize=4)
def _load_model(model_path: str):
    """YOLO 모델 로드(캐시). 가중치 없으면 ultralytics가 자동 다운로드."""
    from ultralytics import YOLO

    return YOLO(model_path)


def _model_for(cfg: Config):
    """가중치를 models/ 디렉터리에 두고 로드.

    전체 경로를 넘기면 ultralytics attempt_download_asset()이 알려진 자산명을
    그 경로 그대로 다운로드한다(downloads.py:504-505 검증). 따라서 CWD 오염 없음.
    """
    cfg.paths.models.mkdir(parents=True, exist_ok=True)
    weights = cfg.paths.models / cfg.detect.model
    return _load_model(str(weights))


def detect_clip(clip_path: Path, cfg: Config) -> list[DetectionEvent]:
    """클립을 sample_fps로 샘플링해 탐지 이벤트 목록 반환. 탐지 없으면 빈 리스트."""
    clip_path = Path(clip_path)
    cap = cv2.VideoCapture(str(clip_path))
    if not cap.isOpened():
        logger.warning("클립 열기 실패 건너뜀: %s", clip_path)
        return []

    video_fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    if video_fps <= 0:
        logger.warning("fps 미상 → 1로 가정: %s", clip_path)
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
            events.extend(_events_from_result(result, clip_path, t_sec, model.names))
        frame_idx += 1

    cap.release()
    logger.info("탐지 %d건: %s (step=%d, device=%s)", len(events), clip_path.name, step, device)
    return events


def _events_from_result(result, clip_path: Path, t_sec: float, names: dict) -> list[DetectionEvent]:
    """단일 프레임 결과를 클래스별로 집계해 이벤트 생성."""
    boxes = result.boxes
    if boxes is None or len(boxes) == 0:
        return []

    # 클래스별 개수/최대 신뢰도 집계
    agg: dict[int, tuple[int, float]] = {}
    for cls_id, conf in zip(boxes.cls.tolist(), boxes.conf.tolist()):
        cid = int(cls_id)
        n, cmax = agg.get(cid, (0, 0.0))
        agg[cid] = (n + 1, max(cmax, float(conf)))

    return [
        DetectionEvent(clip_path, t_sec, cid, str(names.get(cid, cid)), n, round(cmax, 3))
        for cid, (n, cmax) in agg.items()
    ]


if __name__ == "__main__":
    import sys

    from src.config import ensure_dirs, load_config, setup_logging

    cfg = load_config()
    setup_logging(cfg.logging_level)
    ensure_dirs(cfg)

    target = sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures/sample_person.mp4"
    for e in detect_clip(Path(target), cfg):
        print(f"  t={e.t_sec:.1f}s  {e.class_name}(#{e.class_id})  n={e.n}  conf={e.conf}")
