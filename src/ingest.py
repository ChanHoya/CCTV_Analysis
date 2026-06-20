"""Ingest — 입력 영상 수집 / ffprobe 검사 / 비표준 포맷 정규화.

AGENTS.md §5의 검증된 ffprobe·ffmpeg 명령만 사용한다.
손상/0바이트/디코딩 불가 파일은 경고 후 건너뛴다(에러로 중단하지 않음).
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

from src.config import Config

logger = logging.getLogger(__name__)

# 입력으로 받아들일 비디오 확장자
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".m4v", ".mpg", ".mpeg", ".ts", ".webm"}


@dataclass(frozen=True)
class VideoMeta:
    path: Path
    duration_sec: float
    fps: float
    width: int
    height: int
    codec: str
    container: str  # 확장자 기반 (예: "mp4")


def collect_inputs(target: Path | str) -> list[Path]:
    """단일 파일 또는 폴더를 받아 비디오 파일 경로 목록을 반환."""
    target = Path(target)
    if target.is_file():
        return [target]
    if target.is_dir():
        return sorted(
            p for p in target.iterdir()
            if p.is_file() and p.suffix.lower() in VIDEO_EXTS
        )
    logger.warning("입력 경로가 존재하지 않음: %s", target)
    return []


def _parse_fps(r_frame_rate: str) -> float:
    """'10/1' 같은 분수 문자열을 float fps로 변환."""
    try:
        if "/" in r_frame_rate:
            num, den = r_frame_rate.split("/", 1)
            den_f = float(den)
            return float(num) / den_f if den_f else 0.0
        return float(r_frame_rate)
    except (ValueError, ZeroDivisionError):
        return 0.0


def probe(path: Path) -> VideoMeta | None:
    """ffprobe로 메타데이터 추출. 손상/디코딩 불가 시 None + 경고.

    AGENTS.md §5 검증 명령:
      ffprobe -v error -show_entries format=duration:stream=codec_name,width,height,r_frame_rate -of json
    """
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        logger.warning("0바이트/없는 파일 건너뜀: %s", path)
        return None

    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries",
        "format=duration:stream=codec_type,codec_name,width,height,r_frame_rate",
        "-of", "json", str(path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        logger.warning("ffprobe 실패(손상 가능) 건너뜀: %s — %s", path, e.stderr.strip())
        return None

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        logger.warning("ffprobe 출력 파싱 실패 건너뜀: %s", path)
        return None

    video_streams = [
        s for s in data.get("streams", []) if s.get("codec_type") == "video"
    ]
    if not video_streams:
        logger.warning("비디오 스트림 없음 건너뜀: %s", path)
        return None

    vs = video_streams[0]
    duration = float(data.get("format", {}).get("duration", 0.0) or 0.0)
    return VideoMeta(
        path=path,
        duration_sec=duration,
        fps=_parse_fps(vs.get("r_frame_rate", "0/1")),
        width=int(vs.get("width", 0) or 0),
        height=int(vs.get("height", 0) or 0),
        codec=str(vs.get("codec_name", "")).lower(),
        container=path.suffix.lstrip(".").lower(),
    )


def is_standard(meta: VideoMeta, cfg: Config) -> bool:
    """코덱·컨테이너가 config 기준 표준이면 True (정규화 불필요)."""
    return (
        meta.codec in cfg.ingest.standard_codecs
        and meta.container == cfg.ingest.standard_container
    )


def normalize(meta: VideoMeta, cfg: Config) -> Path:
    """비표준 포맷을 표준 MP4(H.264)로 변환. 출력은 uploads 디렉터리.

    AGENTS.md §5 검증 명령: ffmpeg -i <입력> -c:v libx264 -an <표준화.mp4>
    """
    out_path = cfg.paths.uploads / f"{meta.path.stem}.normalized.mp4"
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-i", str(meta.path),
        "-c:v", "libx264", "-an",
        str(out_path),
    ]
    logger.info("정규화: %s (%s) → %s", meta.path.name, meta.codec, out_path.name)
    subprocess.run(cmd, check=True)
    return out_path


def ingest_file(path: Path, cfg: Config) -> VideoMeta | None:
    """단일 파일을 검사하고 필요 시 정규화한 뒤, 처리 대상 VideoMeta 반환.

    손상/디코딩 불가 파일은 None.
    """
    meta = probe(path)
    if meta is None:
        return None

    logger.info(
        "검사: %s | %.1fs %.2ffps %dx%d %s/%s",
        meta.path.name, meta.duration_sec, meta.fps,
        meta.width, meta.height, meta.codec, meta.container,
    )

    if is_standard(meta, cfg):
        return meta

    normalized_path = normalize(meta, cfg)
    return probe(normalized_path)


if __name__ == "__main__":
    import sys

    from src.config import ensure_dirs, load_config, setup_logging

    cfg = load_config()
    setup_logging(cfg.logging_level)
    ensure_dirs(cfg)

    target = sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures"
    for f in collect_inputs(target):
        m = ingest_file(f, cfg)
        if m:
            print(f"OK  {m.path.name}  {m.duration_sec:.1f}s  {m.codec}/{m.container}")
        else:
            print(f"SKIP {f.name}")
