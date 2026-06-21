"""config.yaml 로더 + 스키마 검증.

코드의 모든 튜닝 값은 이 모듈을 통해서만 읽는다 (AGENTS.md §1.3).
외부 스키마 라이브러리 없이 dataclass + 명시적 검증으로 키 누락/타입 오류를 조기에 잡는다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# 프로젝트 루트 = 이 파일(src/config.py)의 부모의 부모
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"


@dataclass(frozen=True)
class Paths:
    uploads: Path
    clips: Path
    thumbs: Path
    db: Path
    models: Path


@dataclass(frozen=True)
class MotionConfig:
    frame_width: int
    blur_radius: int
    threshold: int
    dilate_iterations: int
    min_area: int
    min_event_length: str
    time_before_event: float
    time_post_event: float
    merge_gap_sec: float = 30.0  # 이 간격(초) 미만 연속 이벤트를 하나로 병합
    regions: list[list[int]] = field(default_factory=list)


@dataclass(frozen=True)
class DetectConfig:
    model: str
    sample_fps: float
    classes: list[int]
    conf: float
    device: str
    require_detection: bool = True  # YOLO 확인 없는 이벤트 폐기 여부


@dataclass(frozen=True)
class IngestConfig:
    standard_codecs: list[str]
    standard_container: str
    cleanup_normalized: bool = True


@dataclass(frozen=True)
class NotifyConfig:
    enabled: bool
    webhook_url_env: str
    cooldown_sec: int


@dataclass(frozen=True)
class Config:
    paths: Paths
    motion: MotionConfig
    detect: DetectConfig
    ingest: IngestConfig
    notify: NotifyConfig
    logging_level: str


class ConfigError(ValueError):
    """config.yaml 검증 실패."""


def _require(d: dict, key: str, section: str):
    if key not in d:
        raise ConfigError(f"[{section}] 필수 키 누락: '{key}'")
    return d[key]


def _resolve(p: str) -> Path:
    """config의 상대경로를 프로젝트 루트 기준 절대경로로 변환."""
    path = Path(p)
    return path if path.is_absolute() else (PROJECT_ROOT / path)


def load_config(path: Path | str = DEFAULT_CONFIG_PATH) -> Config:
    cfg_path = Path(path)
    if not cfg_path.exists():
        raise ConfigError(f"config 파일을 찾을 수 없음: {cfg_path}")

    with cfg_path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    if not isinstance(raw, dict):
        raise ConfigError("config.yaml 최상위는 매핑(dict)이어야 함")

    p = _require(raw, "paths", "root")
    paths = Paths(
        uploads=_resolve(_require(p, "uploads", "paths")),
        clips=_resolve(_require(p, "clips", "paths")),
        thumbs=_resolve(_require(p, "thumbs", "paths")),
        db=_resolve(_require(p, "db", "paths")),
        models=_resolve(_require(p, "models", "paths")),
    )

    m = _require(raw, "motion", "root")
    motion = MotionConfig(
        frame_width=int(_require(m, "frame_width", "motion")),
        blur_radius=int(_require(m, "blur_radius", "motion")),
        threshold=int(_require(m, "threshold", "motion")),
        dilate_iterations=int(_require(m, "dilate_iterations", "motion")),
        min_area=int(_require(m, "min_area", "motion")),
        min_event_length=str(_require(m, "min_event_length", "motion")),
        time_before_event=float(_require(m, "time_before_event", "motion")),
        time_post_event=float(_require(m, "time_post_event", "motion")),
        merge_gap_sec=float(m.get("merge_gap_sec", 30.0)),
        regions=list(m.get("regions", []) or []),
    )

    d = _require(raw, "detect", "root")
    detect = DetectConfig(
        model=str(_require(d, "model", "detect")),
        sample_fps=float(_require(d, "sample_fps", "detect")),
        classes=[int(c) for c in _require(d, "classes", "detect")],
        conf=float(_require(d, "conf", "detect")),
        device=str(_require(d, "device", "detect")),
        require_detection=bool(d.get("require_detection", True)),
    )
    if detect.sample_fps <= 0:
        raise ConfigError("[detect] sample_fps는 0보다 커야 함")

    i = _require(raw, "ingest", "root")
    ingest = IngestConfig(
        standard_codecs=[str(c).lower() for c in _require(i, "standard_codecs", "ingest")],
        standard_container=str(_require(i, "standard_container", "ingest")),
        cleanup_normalized=bool(i.get("cleanup_normalized", True)),
    )

    n = _require(raw, "notify", "root")
    notify = NotifyConfig(
        enabled=bool(_require(n, "enabled", "notify")),
        webhook_url_env=str(_require(n, "webhook_url_env", "notify")),
        cooldown_sec=int(_require(n, "cooldown_sec", "notify")),
    )

    log = raw.get("logging", {}) or {}
    logging_level = str(log.get("level", "INFO")).upper()

    return Config(
        paths=paths,
        motion=motion,
        detect=detect,
        ingest=ingest,
        notify=notify,
        logging_level=logging_level,
    )


def setup_logging(level: str = "INFO") -> None:
    """표준 logging 설정 (AGENTS.md §6). 모듈은 logging.getLogger(__name__) 사용."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def ensure_dirs(cfg: Config) -> None:
    """config에 정의된 출력 디렉터리들을 생성(존재하면 무시)."""
    cfg.paths.uploads.mkdir(parents=True, exist_ok=True)
    cfg.paths.clips.mkdir(parents=True, exist_ok=True)
    cfg.paths.thumbs.mkdir(parents=True, exist_ok=True)
    cfg.paths.db.parent.mkdir(parents=True, exist_ok=True)
    cfg.paths.models.mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    c = load_config()
    print("config.yaml 로드 성공:")
    print(f"  paths.uploads = {c.paths.uploads}")
    print(f"  motion.threshold = {c.motion.threshold}")
    print(f"  detect.model = {c.detect.model}, sample_fps = {c.detect.sample_fps}")
    print(f"  detect.classes = {c.detect.classes}, device = {c.detect.device}")
