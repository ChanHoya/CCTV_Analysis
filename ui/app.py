"""Streamlit UI — 영상 분석 실행 + 이벤트/썸네일/클립 확인.

비개발자가 영상을 넣고 결과(타임라인·썸네일·탐지)를 눈으로 확인하는 용도.
실행: streamlit run ui/app.py
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

# 프로젝트 루트를 import 경로에 추가(streamlit이 ui/에서 실행해도 src 임포트 가능)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st  # noqa: E402

from src.config import Config, ensure_dirs, load_config  # noqa: E402
from src.pipeline import process_folder  # noqa: E402
from src.store import connect, get_detections, get_events, get_videos  # noqa: E402

st.set_page_config(page_title="CCTV 모션 분석", layout="wide")


def override_config(base: Config, threshold: float, sample_fps: float, conf: float) -> Config:
    """UI 슬라이더 값을 config에 반영(frozen dataclass라 replace로 새 객체 생성)."""
    motion = replace(base.motion, threshold=threshold)
    detect = replace(base.detect, sample_fps=sample_fps, conf=conf)
    return replace(base, motion=motion, detect=detect)


cfg_base = load_config()
ensure_dirs(cfg_base)

# ---------------- 사이드바: 파라미터 + 입력 ----------------
st.sidebar.header("⚙️ 분석 파라미터")
threshold = st.sidebar.slider(
    "모션 임계값 (낮을수록 민감)", 0.01, 1.0, float(cfg_base.motion.threshold), 0.01
)
sample_fps = st.sidebar.slider(
    "탐지 샘플 fps", 0.5, 5.0, float(cfg_base.detect.sample_fps), 0.5
)
conf = st.sidebar.slider(
    "탐지 신뢰도 임계값", 0.1, 0.9, float(cfg_base.detect.conf), 0.05
)
cfg = override_config(cfg_base, threshold, sample_fps, conf)

st.sidebar.divider()
st.sidebar.header("📂 입력")

uploaded = st.sidebar.file_uploader(
    "영상 업로드", type=["mp4", "mov", "avi", "mkv", "m4v"], accept_multiple_files=True
)
folder = st.sidebar.text_input("또는 폴더 경로", value="tests/fixtures")

if st.sidebar.button("▶ 분석 실행", type="primary"):
    targets: list[str] = []
    if uploaded:
        for uf in uploaded:
            dest = cfg.paths.uploads / uf.name
            dest.write_bytes(uf.getbuffer())
            targets.append(str(dest))
    elif folder.strip():
        targets.append(folder.strip())

    if not targets:
        st.sidebar.error("업로드하거나 폴더 경로를 입력하세요.")
    else:
        with st.spinner("분석 중… (모션 추출 → 객체 탐지)"):
            total_clips = total_dets = 0
            for t in targets:
                for r in process_folder(t, cfg):
                    total_clips += r.n_clips
                    total_dets += r.n_detections
        st.sidebar.success(f"완료: 모션클립 {total_clips}, 탐지 {total_dets}")

# ---------------- 본문: 결과 확인 ----------------
st.title("🎥 CCTV 모션 분석 결과")

conn = connect(cfg)
videos = get_videos(conn)

if not videos:
    st.info("아직 분석된 영상이 없습니다. 사이드바에서 영상을 넣고 ‘분석 실행’을 누르세요.")
    st.stop()

labels = {f"#{v['id']} {Path(v['path']).name}": v for v in videos}
selected_label = st.selectbox("영상 선택", list(labels.keys()))
video = labels[selected_label]

st.caption(
    f"{Path(video['path']).name} · {video['duration_sec']:.1f}s · "
    f"{video['width']}x{video['height']} · {video['codec']}"
)

events = get_events(conn, video["id"])
if not events:
    st.warning("이 영상에서 모션 이벤트가 없습니다.")
    st.stop()

st.subheader(f"모션 이벤트 {len(events)}건 — 썸네일")
cols = st.columns(min(4, len(events)))
for idx, e in enumerate(events):
    with cols[idx % len(cols)]:
        thumb = e["thumbnail_path"]
        if thumb and Path(thumb).exists():
            st.image(thumb, use_container_width=True)
        st.caption(f"이벤트 #{e['id']} · {e['start_sec']:.1f}–{e['end_sec']:.1f}s")

st.divider()
st.subheader("이벤트 상세 — 클립 재생 + 탐지")
ev_labels = {
    f"이벤트 #{e['id']} [{e['start_sec']:.1f}–{e['end_sec']:.1f}s]": e for e in events
}
sel_ev = ev_labels[st.selectbox("이벤트 선택", list(ev_labels.keys()))]

left, right = st.columns([2, 1])
with left:
    clip = sel_ev["clip_path"]
    if clip and Path(clip).exists():
        st.video(clip)
    else:
        st.warning("클립 파일을 찾을 수 없습니다.")
with right:
    dets = get_detections(conn, sel_ev["id"])
    if not dets:
        st.write("탐지된 객체 없음")
    else:
        st.write("**탐지 객체**")
        for d in dets:
            st.write(f"- `{d['class_name']}` × {d['n']} (conf {d['conf']}) @ {d['t_sec']:.1f}s")

conn.close()
