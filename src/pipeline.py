"""Pipeline — ingest → motion → detect → store 오케스트레이션.

아키텍처:
  1. scan_motion (OpenCV absdiff): 클립 파일 없이 모션 타임스탬프만 반환
  2. detect_segment: 원본 영상 구간 직접 YOLO 분석 + 배경 차분 필터로 정지 객체 제외
  3. 썸네일: ffmpeg으로 원본 영상 중간 프레임 추출
  4. 저장: clip_path = 원본 영상 경로 (별도 클립 파일 없음)
"""

from __future__ import annotations

import logging
import sqlite3
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from src.config import Config, ensure_dirs, load_config, setup_logging
from src.detect import detect_segment
from src.ingest import collect_inputs, ingest_file
from src.motion import MotionClip, scan_motion
from src.store import (
    clear_video_results,
    connect,
    init_db,
    save_detections,
    save_motion_event,
    sha256_file,
    upsert_video,
)

logger = logging.getLogger(__name__)

ProgressCb = Callable[[float, str], None] | None


@dataclass
class FileResult:
    path: Path
    ok: bool
    n_clips: int = 0
    n_raw_clips: int = 0       # YOLO 필터 전 원본 모션 수
    n_detections: int = 0
    elapsed_sec: float = 0.0
    error: str | None = None


def _extract_thumb(video_path: Path, at_sec: float, out_path: Path) -> bool:
    """원본 영상의 at_sec 위치 프레임을 JPEG로 추출."""
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-ss", f"{at_sec:.3f}", "-i", str(video_path),
             "-frames:v", "1", "-q:v", "4", str(out_path)],
            capture_output=True, check=True,
        )
        return out_path.exists()
    except Exception:
        return False


def process_file(
    path: Path,
    cfg: Config,
    conn: sqlite3.Connection,
    progress_cb: ProgressCb = None,
    stop_event: threading.Event | None = None,
) -> FileResult:
    """단일 영상 end-to-end 처리. idempotent(SHA 기준 결과 교체)."""

    def _cb(p: float, msg: str) -> None:
        if progress_cb:
            progress_cb(p, msg)

    def _stopped() -> bool:
        return stop_event is not None and stop_event.is_set()

    path = Path(path)
    start = time.perf_counter()

    _cb(0.02, f"영상 확인 중… {path.name}")
    sha = sha256_file(path)
    meta = ingest_file(path, cfg)
    if meta is None:
        return FileResult(path, ok=False, error="ingest 실패(손상/디코딩 불가)",
                          elapsed_sec=time.perf_counter() - start)

    _cb(0.08, "영상 준비 완료 — 모션 추출 시작")
    video_id = upsert_video(conn, meta, sha)
    clear_video_results(conn, video_id)

    # ── Phase 1: OpenCV 모션 감지 (클립 미생성) ──
    _cb(0.12, "모션 구간 추출 중… (OpenCV absdiff)")

    def _scan_cb(p: float, msg: str) -> None:
        _cb(0.12 + 0.33 * p, msg)

    events = scan_motion(
        meta.path, cfg,
        progress_cb=_scan_cb,
        video_duration=getattr(meta, "duration_sec", 0.0),
    )
    n_total = len(events)
    _cb(0.45, f"모션 구간 {n_total}건 추출 완료 — 객체 탐지 시작")

    # ── Phase 2: 원본 영상 구간별 YOLO (배경 차분 필터 포함) ──
    n_confirmed = 0
    n_dets = 0

    for i, (start_sec, end_sec) in enumerate(events):
        if _stopped():
            logger.info("분석 중단 요청 — 남은 이벤트 건너뜀")
            break

        clip_progress = 0.45 + 0.50 * (i / max(n_total, 1))
        _cb(clip_progress, f"객체 탐지 중… [{i + 1}/{n_total}] ({start_sec:.0f}s~{end_sec:.0f}s)")

        dets = detect_segment(path, start_sec, end_sec, cfg)

        # YOLO 확인 필터
        if cfg.detect.require_detection and not dets:
            logger.info("움직이는 객체 없음 — 건너뜀: %.1f~%.1fs", start_sec, end_sec)
            continue

        # 썸네일: 구간 중간 프레임
        mid = (start_sec + end_sec) / 2
        thumb_dest = cfg.paths.thumbs / f"{path.stem}_{int(start_sec * 10):09d}.jpg"
        _extract_thumb(path, mid, thumb_dest)

        clip = MotionClip(
            clip_path=path,                                        # 원본 영상 경로
            thumbnail_path=thumb_dest if thumb_dest.exists() else None,
            start_sec=start_sec,
            end_sec=end_sec,
        )
        event_id = save_motion_event(conn, video_id, clip)
        save_detections(conn, event_id, dets)
        n_dets += len(dets)
        n_confirmed += 1

    _cb(0.97, "결과 저장 중…")
    conn.commit()

    noise_filtered = n_total - n_confirmed
    if noise_filtered:
        logger.info("정지 객체 / 노이즈 제거: %d건 / 전체 %d건", noise_filtered, n_total)

    # 정규화 중간 파일 정리
    if meta.path.resolve() != path.resolve() and cfg.ingest.cleanup_normalized and meta.path.exists():
        meta.path.unlink()

    _cb(1.0, f"완료 — 이벤트 {n_confirmed}건 확인, 탐지 {n_dets}건")
    return FileResult(path, ok=True, n_clips=n_confirmed, n_raw_clips=n_total,
                      n_detections=n_dets, elapsed_sec=time.perf_counter() - start)


def process_folder(
    target: Path | str,
    cfg: Config,
    progress_cb: ProgressCb = None,
    stop_event: threading.Event | None = None,
) -> list[FileResult]:
    """폴더(또는 단일 파일)의 모든 영상을 end-to-end 처리."""
    ensure_dirs(cfg)
    inputs = collect_inputs(target)
    if not inputs:
        logger.warning("처리할 영상이 없음: %s", target)
        return []

    conn = connect(cfg)
    init_db(conn)

    results: list[FileResult] = []
    total = len(inputs)
    t0 = time.perf_counter()

    for i, path in enumerate(inputs, 1):
        if stop_event and stop_event.is_set():
            logger.info("분석 중단 — 남은 파일 건너뜀")
            break

        logger.info("[%d/%d] 처리 시작: %s", i, total, path.name)
        seg_s = (i - 1) / total
        seg_e = i / total

        def make_cb(s: float, e: float, fi: int, ft: int) -> ProgressCb:
            def _file_cb(p: float, msg: str) -> None:
                if progress_cb:
                    progress_cb(s + (e - s) * p, f"[{fi}/{ft}] {msg}")
            return _file_cb

        try:
            res = process_file(path, cfg, conn, make_cb(seg_s, seg_e, i, total), stop_event)
        except Exception as exc:
            logger.exception("[%d/%d] 처리 실패(건너뜀): %s", i, total, path.name)
            res = FileResult(path, ok=False, error=str(exc))

        results.append(res)
        if res.ok:
            logger.info("[%d/%d] 완료: %s — 이벤트 %d, 탐지 %d (%.1fs)",
                        i, total, path.name, res.n_clips, res.n_detections, res.elapsed_sec)

    conn.close()
    ok = sum(1 for r in results if r.ok)
    clips = sum(r.n_clips for r in results)
    dets = sum(r.n_detections for r in results)
    logger.info("배치 완료: 성공 %d/%d, 이벤트 %d, 탐지 %d, 총 %.1fs",
                ok, total, clips, dets, time.perf_counter() - t0)
    return results


def main() -> None:
    import sys
    cfg = load_config()
    setup_logging(cfg.logging_level)
    target = sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures"
    process_folder(target, cfg)


if __name__ == "__main__":
    main()
