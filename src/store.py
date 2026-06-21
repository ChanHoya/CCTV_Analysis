"""Store — SQLite로 영상/모션이벤트/탐지 저장 및 조회.

관계: videos 1—N motion_events 1—N detections (FK ON DELETE CASCADE).
재실행 idempotent: videos.sha256 UNIQUE. 재처리 시 기존 결과를 지우고 재삽입.
AGENTS.md §7: 프레임 픽셀은 저장하지 않고 경로만 기록.
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

from src.config import Config

if TYPE_CHECKING:  # 런타임 무거운 모듈 import 회피(타입 힌트 전용)
    from src.detect import DetectionEvent
    from src.ingest import VideoMeta
    from src.motion import MotionClip

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    id           INTEGER PRIMARY KEY,
    path         TEXT NOT NULL,
    sha256       TEXT NOT NULL UNIQUE,
    duration_sec REAL,
    fps          REAL,
    width        INTEGER,
    height       INTEGER,
    codec        TEXT,
    container    TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS motion_events (
    id             INTEGER PRIMARY KEY,
    video_id       INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    clip_path      TEXT NOT NULL,
    thumbnail_path TEXT,
    start_sec      REAL,
    end_sec        REAL,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS detections (
    id              INTEGER PRIMARY KEY,
    motion_event_id INTEGER NOT NULL REFERENCES motion_events(id) ON DELETE CASCADE,
    t_sec           REAL,
    class_id        INTEGER,
    class_name      TEXT,
    n               INTEGER,
    conf            REAL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_events_video ON motion_events(video_id);
CREATE INDEX IF NOT EXISTS idx_detections_event ON detections(motion_event_id);
"""


def connect(cfg: Config) -> sqlite3.Connection:
    cfg.paths.db.parent.mkdir(parents=True, exist_ok=True)
    # Enable WAL mode and 60-second busy timeout to avoid database lock issues
    conn = sqlite3.connect(cfg.paths.db, timeout=60.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn



def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    """파일 내용 SHA-256(스트리밍). 동일 영상 재처리 식별용."""
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def get_video_id(conn: sqlite3.Connection, sha: str) -> int | None:
    row = conn.execute("SELECT id FROM videos WHERE sha256 = ?", (sha,)).fetchone()
    return int(row["id"]) if row else None


def upsert_video(conn: sqlite3.Connection, meta: "VideoMeta", sha: str) -> int:
    """영상 행을 보장하고 id 반환. 이미 있으면 메타 갱신 후 기존 id."""
    existing = get_video_id(conn, sha)
    if existing is not None:
        conn.execute(
            "UPDATE videos SET path=?, duration_sec=?, fps=?, width=?, height=?, "
            "codec=?, container=? WHERE id=?",
            (str(meta.path), meta.duration_sec, meta.fps, meta.width, meta.height,
             meta.codec, meta.container, existing),
        )
        conn.commit()
        return existing

    cur = conn.execute(
        "INSERT INTO videos (path, sha256, duration_sec, fps, width, height, codec, container) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (str(meta.path), sha, meta.duration_sec, meta.fps, meta.width, meta.height,
         meta.codec, meta.container),
    )
    conn.commit()
    return int(cur.lastrowid)


def clear_video_results(conn: sqlite3.Connection, video_id: int) -> None:
    """재처리 전 해당 영상의 모션이벤트(+탐지 CASCADE)를 삭제."""
    conn.execute("DELETE FROM motion_events WHERE video_id = ?", (video_id,))
    conn.commit()


def save_motion_event(conn: sqlite3.Connection, video_id: int, clip: "MotionClip") -> int:
    cur = conn.execute(
        "INSERT INTO motion_events (video_id, clip_path, thumbnail_path, start_sec, end_sec) "
        "VALUES (?, ?, ?, ?, ?)",
        (video_id, str(clip.clip_path),
         str(clip.thumbnail_path) if clip.thumbnail_path else None,
         clip.start_sec, clip.end_sec),
    )
    return int(cur.lastrowid)


def save_detections(conn: sqlite3.Connection, event_id: int, dets: list["DetectionEvent"]) -> None:
    conn.executemany(
        "INSERT INTO detections (motion_event_id, t_sec, class_id, class_name, n, conf) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [(event_id, d.t_sec, d.class_id, d.class_name, d.n, d.conf) for d in dets],
    )


# --- 조회 (UI/검증용) ---

def get_videos(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM videos ORDER BY created_at DESC").fetchall()


def get_events(conn: sqlite3.Connection, video_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM motion_events WHERE video_id = ? ORDER BY start_sec", (video_id,)
    ).fetchall()


def get_detections(conn: sqlite3.Connection, event_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM detections WHERE motion_event_id = ? ORDER BY t_sec", (event_id,)
    ).fetchall()


if __name__ == "__main__":
    # 스모크: 더미 데이터 저장 → 재조회 → idempotent 재처리 확인
    from dataclasses import dataclass

    from src.config import ensure_dirs, load_config, setup_logging

    cfg = load_config()
    setup_logging(cfg.logging_level)
    ensure_dirs(cfg)

    @dataclass
    class _Meta:
        path: Path; duration_sec: float; fps: float; width: int
        height: int; codec: str; container: str

    @dataclass
    class _Clip:
        clip_path: Path; thumbnail_path: Path | None; start_sec: float; end_sec: float

    @dataclass
    class _Det:
        clip_path: Path; t_sec: float; class_id: int; class_name: str; n: int; conf: float

    conn = connect(cfg)
    init_db(conn)

    meta = _Meta(Path("tests/fixtures/sample_person.mp4"), 3.0, 5.0, 640, 480, "h264", "mp4")
    sha = "deadbeef_smoke"
    vid = upsert_video(conn, meta, sha)  # type: ignore[arg-type]
    clear_video_results(conn, vid)
    eid = save_motion_event(conn, vid, _Clip(Path("data/clips/x.mp4"), Path("data/thumbs/x.jpg"), 0.2, 6.0))  # type: ignore[arg-type]
    save_detections(conn, eid, [_Det(Path("data/clips/x.mp4"), 0.0, 0, "person", 4, 0.886)])  # type: ignore[arg-type]
    conn.commit()

    # 재조회
    for v in get_videos(conn):
        print(f"video #{v['id']} {Path(v['path']).name} sha={v['sha256'][:8]}")
        for e in get_events(conn, v["id"]):
            print(f"  event #{e['id']} {e['start_sec']}–{e['end_sec']}s clip={Path(e['clip_path']).name}")
            for d in get_detections(conn, e["id"]):
                print(f"    det {d['class_name']} n={d['n']} conf={d['conf']} @ {d['t_sec']}s")

    # idempotent 재처리: 같은 sha → 같은 video_id, 이벤트 1건 유지
    vid2 = upsert_video(conn, meta, sha)  # type: ignore[arg-type]
    clear_video_results(conn, vid2)
    save_motion_event(conn, vid2, _Clip(Path("data/clips/x.mp4"), None, 0.2, 6.0))  # type: ignore[arg-type]
    conn.commit()
    n_videos = len(get_videos(conn))
    n_events = len(get_events(conn, vid2))
    print(f"재처리 후: video_id 동일={vid == vid2}, videos={n_videos}, events={n_events}")
    conn.close()
