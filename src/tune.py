"""Tune — 실제 영상으로 모션 threshold를 스윕해 최적값 탐색 (OpenCV 기반).

순수 OpenCV scan_motion 알고리즘을 사용하여 별도 프로세스 없이 고속으로 임계값을 스윕합니다.
환경별로 적정 threshold를 고른 뒤 config.yaml에 반영하고 docs/TUNING.md에 기록합니다.

사용: python -m src.tune <video> [t1 t2 t3 ...]
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass, replace
from pathlib import Path

from src.config import Config, load_config, setup_logging
from src.motion import scan_motion

logger = logging.getLogger(__name__)

# OpenCV absdiff 방식에 적합한 기본 정수 임계값 목록 (0~255 범위)
DEFAULT_THRESHOLDS = [5, 10, 15, 20, 25, 30, 40, 50, 70]


@dataclass(frozen=True)
class SweepRow:
    threshold: float
    n_events: int
    total_motion_sec: float


def sweep_threshold(video: Path, cfg: Config, thresholds: list[int]) -> list[SweepRow]:
    """각 threshold 값으로 OpenCV scan_motion 실행 → 이벤트 수/총 모션시간 측정."""
    rows: list[SweepRow] = []
    for t in thresholds:
        # 임시 설정 반영을 위해 dataclass replace 사용
        temp_motion = replace(cfg.motion, threshold=t)
        temp_cfg = replace(cfg, motion=temp_motion)

        events = scan_motion(video, temp_cfg)
        total = sum(end - start for start, end in events)
        rows.append(SweepRow(float(t), len(events), round(total, 2)))
        logger.info("t=%-5d → 이벤트 %d건, 총 모션 %.1fs", t, len(events), total)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="모션 threshold 스윕 튜닝")
    parser.add_argument("video", type=Path, help="튜닝 대상 영상")
    parser.add_argument("thresholds", nargs="*", type=int, help="시험할 threshold 값들 (정수 0~255)")
    args = parser.parse_args()

    cfg = load_config()
    setup_logging(cfg.logging_level)
    thresholds = args.thresholds or DEFAULT_THRESHOLDS

    print(f"\n[튜닝 대상] {args.video}  (frame_width={cfg.motion.frame_width}, min_area={cfg.motion.min_area})")
    rows = sweep_threshold(args.video, cfg, thresholds)
    print("\n  threshold | 이벤트수 | 총 모션(초)")
    print("  ----------+----------+-----------")
    for r in rows:
        print(f"  {int(r.threshold):>9} | {r.n_events:>8} | {r.total_motion_sec:>9}")
    print("\n과탐(이벤트 폭증)과 미탐(0건) 사이의 안정 구간을 골라 config.yaml motion.threshold에 반영하세요.")


if __name__ == "__main__":
    main()
