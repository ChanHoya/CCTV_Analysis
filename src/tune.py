"""Tune — 실제 영상으로 모션 threshold를 스윕해 최적값 탐색(읽기 전용).

DVR-Scan scan-only(-so) 모드로 클립을 쓰지 않고 이벤트 수/총 모션시간만 측정한다.
환경별로 적정 threshold를 고른 뒤 config.yaml에 반영하고 docs/TUNING.md에 기록한다.

사용: python -m src.tune <video> [t1 t2 t3 ...]
"""

from __future__ import annotations

import argparse
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

from src.config import Config, load_config, setup_logging
from src.motion import _dvr_scan_bin, _parse_event_times, _region_args

logger = logging.getLogger(__name__)

DEFAULT_THRESHOLDS = [0.05, 0.1, 0.15, 0.2, 0.3, 0.5]


@dataclass(frozen=True)
class SweepRow:
    threshold: float
    n_events: int
    total_motion_sec: float


def sweep_threshold(video: Path, cfg: Config, thresholds: list[float]) -> list[SweepRow]:
    """각 threshold로 scan-only 실행 → 이벤트 수/총 모션시간 측정."""
    rows: list[SweepRow] = []
    for t in thresholds:
        cmd = [
            _dvr_scan_bin(),
            "-i", str(video),
            "-so",                       # scan-only: 파일 미기록
            "-b", cfg.motion.bg_subtractor,
            "-t", str(t),
            "-k", str(cfg.motion.kernel_size),
            "-l", str(cfg.motion.min_event_length),
            "-tb", f"{cfg.motion.time_before_event}s",
            "-tp", f"{cfg.motion.time_post_event}s",
            *_region_args(cfg),
            "-q",
        ]
        if cfg.motion.downscale_factor and cfg.motion.downscale_factor > 1:
            cmd.extend(["-df", str(cfg.motion.downscale_factor)])

        out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.strip()
        events = _parse_event_times(out) if out else []
        total = sum(end - start for start, end in events)
        rows.append(SweepRow(t, len(events), round(total, 2)))
        logger.info("t=%-5s → 이벤트 %d건, 총 모션 %.1fs", t, len(events), total)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="모션 threshold 스윕 튜닝")
    parser.add_argument("video", type=Path, help="튜닝 대상 영상")
    parser.add_argument("thresholds", nargs="*", type=float, help="시험할 threshold 값들")
    args = parser.parse_args()

    cfg = load_config()
    setup_logging(cfg.logging_level)
    thresholds = args.thresholds or DEFAULT_THRESHOLDS

    print(f"\n튜닝 대상: {args.video}  (bg={cfg.motion.bg_subtractor}, k={cfg.motion.kernel_size})")
    rows = sweep_threshold(args.video, cfg, thresholds)
    print("\n  threshold | 이벤트수 | 총 모션(초)")
    print("  ----------+----------+-----------")
    for r in rows:
        print(f"  {r.threshold:>9} | {r.n_events:>8} | {r.total_motion_sec:>9}")
    print("\n과탐(이벤트 폭증)과 미탐(0건) 사이의 안정 구간을 골라 config.yaml motion.threshold에 반영하세요.")


if __name__ == "__main__":
    main()
