"""Pipeline — ingest → motion → detect → store 오케스트레이션.

폴더 내 다중 영상을 배치 처리하며 진행률/소요시간/이벤트 수를 로깅한다.
파일 단위로 격리: 한 영상이 실패해도 다음 영상 처리를 계속한다(AGENTS.md §5 DoD).
"""

from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass, replace
from pathlib import Path

from src.config import Config, ensure_dirs, load_config, setup_logging
from src.detect import detect_clip
from src.ingest import collect_inputs, ingest_file
from src.motion import scan_motion
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


@dataclass
class FileResult:
    path: Path
    ok: bool
    n_clips: int = 0
    n_detections: int = 0
    elapsed_sec: float = 0.0
    error: str | None = None


def process_file(path: Path, cfg: Config, conn: sqlite3.Connection) -> FileResult:
    """단일 영상: 검사→정규화→모션→탐지→저장. idempotent(SHA 기준 결과 교체)."""
    path = Path(path)
    start = time.perf_counter()

    sha = sha256_file(path)  # 원본 기준 식별(재처리 시 동일 video로 매핑)
    meta = ingest_file(path, cfg)
    if meta is None:
        return FileResult(path, ok=False, error="ingest 실패(손상/디코딩 불가)",
                          elapsed_sec=time.perf_counter() - start)

    # 정규화된 경우 모션은 normalized로 돌리되, DB에는 영속하는 원본 경로를 저장
    # (normalized 임시파일은 처리 후 정리되므로 dangling 방지)
    db_meta = replace(meta, path=path) if meta.path.resolve() != path.resolve() else meta
    video_id = upsert_video(conn, db_meta, sha)
    clear_video_results(conn, video_id)  # 재처리 시 이전 결과 제거

    clips = scan_motion(meta.path, cfg)
    n_dets = 0
    for clip in clips:
        event_id = save_motion_event(conn, video_id, clip)
        dets = detect_clip(clip.clip_path, cfg)
        save_detections(conn, event_id, dets)
        n_dets += len(dets)
    conn.commit()

    # 정규화 중간 파일 정리(클립은 이미 별도 추출됨) — 디스크 절약 (Phase 8)
    was_normalized = meta.path.resolve() != path.resolve()
    if was_normalized and cfg.ingest.cleanup_normalized and meta.path.exists():
        meta.path.unlink()
        logger.info("정규화 임시파일 삭제: %s", meta.path.name)

    return FileResult(path, ok=True, n_clips=len(clips), n_detections=n_dets,
                      elapsed_sec=time.perf_counter() - start)


def process_folder(target: Path | str, cfg: Config) -> list[FileResult]:
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
        logger.info("[%d/%d] 처리 시작: %s", i, total, path.name)
        try:
            res = process_file(path, cfg, conn)
        except Exception as e:  # 파일 단위 격리: 실패해도 다음 파일 계속
            logger.exception("[%d/%d] 처리 실패(건너뜀): %s", i, total, path.name)
            res = FileResult(path, ok=False, error=str(e))
        results.append(res)
        if res.ok:
            logger.info("[%d/%d] 완료: %s — 클립 %d, 탐지 %d (%.1fs)",
                        i, total, path.name, res.n_clips, res.n_detections, res.elapsed_sec)

    conn.close()
    ok = sum(1 for r in results if r.ok)
    clips = sum(r.n_clips for r in results)
    dets = sum(r.n_detections for r in results)
    logger.info("배치 완료: 성공 %d/%d, 모션클립 %d, 탐지 %d, 총 %.1fs",
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
