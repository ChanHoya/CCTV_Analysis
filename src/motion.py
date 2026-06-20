"""Motion — DVR-Scan으로 모션 구간을 추출해 클립 + 썸네일 생성.

AGENTS.md §1.2: DVR-Scan CLI 플래그는 설치 버전(1.8.2.1) `--help`로 검증함.
검증 결과 AGENTS.md §5 예시의 `-o <dir>`는 실제로는 단일 .avi 파일용이며,
디렉터리에 이벤트별 개별 클립을 쓰려면 `-d/--output-dir`를 사용해야 한다.

핵심 플래그(검증됨):
  -d  출력 디렉터리(이벤트별 개별 파일)   -m ffmpeg  무손실 copy 계열 출력
  -t  threshold (낮을수록 민감)          -l  min-event-length (frames|12.3s|timecode)
  -tb time-before-event (s)             -tp time-post-event (s)
  -a  ROI 다각형(3점 이상)               --thumbnails <method>  대표 썸네일
  -q  최종 CSV(start,end,start,end...)만 stdout 출력
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from src.config import Config

logger = logging.getLogger(__name__)

THUMBNAIL_METHOD = "highscore"  # AGENTS.md §5; 1.8.2.1에서 수용 확인


def _dvr_scan_bin() -> str:
    """현재 Python과 동일한 venv의 dvr-scan을 우선, 없으면 PATH에서 탐색."""
    candidate = Path(sys.executable).parent / "dvr-scan"
    if candidate.exists():
        return str(candidate)
    found = shutil.which("dvr-scan")
    if found:
        return found
    raise FileNotFoundError("dvr-scan 실행파일을 찾을 수 없음 (의존성 설치 확인)")


@dataclass(frozen=True)
class MotionClip:
    clip_path: Path
    thumbnail_path: Path | None
    start_sec: float
    end_sec: float


def _timecode_to_sec(tc: str) -> float:
    """'HH:MM:SS.mmm' → 초(float)."""
    h, m, s = tc.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def _parse_event_times(csv_line: str) -> list[tuple[float, float]]:
    """DVR-Scan -q CSV(start1,end1,start2,end2,...) → [(start, end), ...]."""
    parts = [p.strip() for p in csv_line.strip().split(",") if p.strip()]
    secs = [_timecode_to_sec(p) for p in parts]
    return list(zip(secs[0::2], secs[1::2]))


def _clear_previous(stem: str, cfg: Config) -> None:
    """이 영상의 이전 DSME 산출물 제거(파생물이므로 재생성 안전, idempotent)."""
    for p in cfg.paths.clips.glob(f"{stem}.DSME_*"):
        p.unlink()
    for p in cfg.paths.thumbs.glob(f"{stem}.DSME_*"):
        p.unlink()


def _region_args(cfg: Config) -> list[str]:
    args: list[str] = []
    for polygon in cfg.motion.regions:
        if len(polygon) < 6:  # 최소 3점(=6좌표) 필요
            logger.warning("ROI 다각형은 3점 이상이어야 함, 건너뜀: %s", polygon)
            continue
        args.append("-a")
        args.extend(str(int(c)) for c in polygon)
    return args


def scan_motion(video_path: Path, cfg: Config) -> list[MotionClip]:
    """영상에서 모션 구간을 추출. 모션 없으면 빈 리스트(에러 아님)."""
    video_path = Path(video_path)
    stem = video_path.stem
    cfg.paths.clips.mkdir(parents=True, exist_ok=True)
    cfg.paths.thumbs.mkdir(parents=True, exist_ok=True)
    _clear_previous(stem, cfg)

    cmd = [
        _dvr_scan_bin(),
        "-i", str(video_path),
        "-d", str(cfg.paths.clips),
        "-m", "ffmpeg",
        "-b", cfg.motion.bg_subtractor,
        "-t", str(cfg.motion.threshold),
        "-k", str(cfg.motion.kernel_size),
        "-l", str(cfg.motion.min_event_length),
        "-tb", f"{cfg.motion.time_before_event}s",
        "-tp", f"{cfg.motion.time_post_event}s",
        "--thumbnails", THUMBNAIL_METHOD,
        *_region_args(cfg),
        "-q",
    ]
    if cfg.motion.downscale_factor and cfg.motion.downscale_factor > 1:
        cmd.extend(["-df", str(cfg.motion.downscale_factor)])
    logger.info("모션 스캔: %s (t=%s)", video_path.name, cfg.motion.threshold)
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)

    csv_line = result.stdout.strip()
    if not csv_line:
        logger.info("모션 없음: %s", video_path.name)
        return []

    events = _parse_event_times(csv_line)
    clip_files = sorted(cfg.paths.clips.glob(f"{stem}.DSME_*.mp4"))

    clips: list[MotionClip] = []
    for idx, clip_file in enumerate(clip_files):
        # 썸네일을 thumbs 디렉터리로 이동(클립과 동일 인덱스 이름)
        thumb_src = clip_file.with_suffix(".jpg")
        thumb_path: Path | None = None
        if thumb_src.exists():
            thumb_path = cfg.paths.thumbs / thumb_src.name
            thumb_src.replace(thumb_path)
        start, end = events[idx] if idx < len(events) else (0.0, 0.0)
        clips.append(MotionClip(clip_file, thumb_path, start, end))

    logger.info("모션 이벤트 %d건: %s", len(clips), video_path.name)
    return clips


if __name__ == "__main__":
    import sys

    from src.config import ensure_dirs, load_config, setup_logging

    cfg = load_config()
    setup_logging(cfg.logging_level)
    ensure_dirs(cfg)

    target = sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures/sample_motion.mp4"
    for c in scan_motion(Path(target), cfg):
        print(f"  {c.clip_path.name}  [{c.start_sec:.1f}s–{c.end_sec:.1f}s]  thumb={c.thumbnail_path.name if c.thumbnail_path else None}")
