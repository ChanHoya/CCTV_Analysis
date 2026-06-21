"""Streamlit UI — 영상 분석 실행 + 이벤트/썸네일/클립 확인.

사이드바 대신 2컬럼 레이아웃 사용 (접힘 문제 원천 제거).
"""

from __future__ import annotations

import sys
import threading
import time as _time
from dataclasses import replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st  # noqa: E402

from src.config import Config, ensure_dirs, load_config  # noqa: E402
from src.pipeline import process_folder  # noqa: E402
from src.store import connect, get_detections, get_events, get_videos  # noqa: E402

st.set_page_config(page_title="CCTV Analysis System", layout="wide",
                   initial_sidebar_state="collapsed")

st.markdown("""
<style>
/* ── 헤더·사이드바·Deploy 완전 제거 ── */
header[data-testid="stHeader"]  { display: none !important; }
section[data-testid="stSidebar"]{ display: none !important; }
[data-testid="collapsedControl"]{ display: none !important; }
[data-testid="stDeployButton"]  { display: none !important; }
/* ── 메인 패딩 최소화 ── */
.block-container { padding-top: 0.5rem !important; padding-left: 0.8rem !important; padding-right: 0.8rem !important; }
/* ── 좌측 컨트롤 패널 스타일 ── */
.ctrl-panel {
    background: #0f172a;
    border: 1px solid #1e293b;
    border-radius: 8px;
    padding: 0.6rem 0.7rem;
    position: sticky;
    top: 0.5rem;
}
/* ── 컨트롤 패널 내 슬라이더 압축 ── */
.ctrl-panel .stSlider, .ctrl-panel .stSelectSlider {
    margin-bottom: 0 !important; padding-bottom: 0 !important;
}
/* 슬라이더 레이블 소형화 */
div[data-testid="column"]:first-child .stSlider > label,
div[data-testid="column"]:first-child .stSelectSlider > label {
    font-size: 0.72rem !important; color: #94a3b8 !important;
    line-height: 1.2 !important; margin-bottom: 0 !important;
}
div[data-testid="column"]:first-child .stSlider [data-baseweb="slider"],
div[data-testid="column"]:first-child .stSelectSlider [data-baseweb="slider"] {
    padding-top: 0.2rem !important; padding-bottom: 0.05rem !important;
}
div[data-testid="column"]:first-child .element-container { margin-bottom: 0.05rem !important; }
div[data-testid="column"]:first-child .stTooltipHoverTarget { display: none !important; }
/* 파일 업로더 압축 */
div[data-testid="column"]:first-child .stFileUploader > label { font-size: 0.72rem !important; color: #94a3b8 !important; }
div[data-testid="column"]:first-child .stFileUploader [data-testid="stFileUploaderDropzone"] {
    padding: 0.4rem !important; min-height: 2.2rem !important;
}
div[data-testid="column"]:first-child .stFileUploader [data-testid="stFileUploaderDropzone"] p {
    font-size: 0.72rem !important; margin: 0 !important;
}
div[data-testid="column"]:first-child .stAlert { padding: 0.3rem 0.5rem !important; font-size: 0.72rem !important; }
div[data-testid="column"]:first-child .stCaption { font-size: 0.68rem !important; margin: 0.15rem 0 0.05rem !important; }
/* ── 썸네일 카드 ── */
.clip-card { border: 2px solid #1e293b; border-radius: 8px; overflow: hidden; cursor: pointer; }
</style>
""", unsafe_allow_html=True)

# ── 분석 중 애니메이션 ──
_ANALYZING_HEADER = """
<div style="text-align:center;padding:3rem 0 0.5rem;">
  <div style="position:relative;width:100px;height:100px;margin:0 auto 1rem;">
    <div style="position:absolute;border-radius:50%;border:2px solid rgba(59,130,246,0.9);
                animation:cctv-ring 2s ease-out infinite;width:50px;height:50px;top:25px;left:25px;"></div>
    <div style="position:absolute;border-radius:50%;border:2px solid rgba(99,102,241,0.6);
                animation:cctv-ring 2s ease-out infinite;width:75px;height:75px;top:12.5px;left:12.5px;animation-delay:0.65s;"></div>
    <div style="position:absolute;border-radius:50%;border:2px solid rgba(59,130,246,0.25);
                animation:cctv-ring 2s ease-out infinite;width:100px;height:100px;top:0;left:0;animation-delay:1.3s;"></div>
    <div style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);
                font-size:2.2rem;animation:cctv-pulse 1.5s ease-in-out infinite;">📹</div>
  </div>
  <div style="font-size:1.5rem;font-weight:800;letter-spacing:0.12em;color:#f1f5f9;">분석 중</div>
</div>
<style>
@keyframes cctv-ring  { 0%{transform:scale(.8);opacity:.9} 100%{transform:scale(1.4);opacity:0} }
@keyframes cctv-pulse { 0%,100%{opacity:1;transform:translate(-50%,-50%) scale(1)} 50%{opacity:.6;transform:translate(-50%,-50%) scale(.85)} }
</style>"""

_LOGO_HTML = """
<div style="display:flex;flex-direction:column;justify-content:center;align-items:center;height:80vh;">
  <div style="text-align:center;user-select:none;">
    <div style="font-size:5rem;font-weight:900;letter-spacing:0.18em;color:#ffffff;line-height:1.0;
                text-shadow:0 0 40px rgba(99,102,241,0.5);">CCTV</div>
    <div style="font-size:1.7rem;font-weight:600;letter-spacing:0.45em;color:#cbd5e1;margin-top:0.3em;">ANALYSIS SYSTEM</div>
    <div style="width:80px;height:3px;margin:1.2em auto;
                background:linear-gradient(90deg,#3b82f6,#6366f1);border-radius:2px;
                box-shadow:0 0 12px rgba(99,102,241,0.6);"></div>
    <div style="font-size:0.85rem;color:#64748b;letter-spacing:0.15em;">영상을 업로드하고 분석을 실행하세요</div>
  </div>
</div>"""


def override_config(base: Config, threshold: int, sample_fps: float, conf: float,
                    frame_width: int, min_area: int, merge_gap: float) -> Config:
    motion = replace(base.motion, threshold=threshold, frame_width=frame_width,
                     min_area=min_area, merge_gap_sec=merge_gap)
    detect = replace(base.detect, sample_fps=sample_fps, conf=conf)
    return replace(base, motion=motion, detect=detect)


def fmt_time(sec: float) -> str:
    m, s = divmod(int(sec), 60)
    return f"{m:02d}:{s:02d}"


cfg_base = load_config()
ensure_dirs(cfg_base)

# ── 세션 상태 초기화 ──
for k, v in {
    "analyzing": False, "analysis_done": False, "pending_targets": [],
    "analysis_summary": "", "analysis_state": {}, "analysis_thread": None,
    "stop_event": None, "selected_event_idx": 0,
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ════════════════════════════════════════════
#  2컬럼 레이아웃: 좌(컨트롤) + 우(메인)
# ════════════════════════════════════════════
ctrl_col, main_col = st.columns([1, 4], gap="small")

# ── 좌측 컨트롤 패널 ──────────────────────
with ctrl_col:
    # 실행 / 중단 버튼
    _run_clicked = False
    if st.session_state.analyzing:
        if st.button("⏹ 분석 중단", type="secondary", use_container_width=True):
            stop_ev = st.session_state.get("stop_event")
            if stop_ev:
                stop_ev.set()
            st.session_state.analyzing = False
            st.session_state.analysis_thread = None
            st.session_state.analysis_state = {}
            st.session_state.analysis_summary = "분석이 중단되었습니다."
            st.rerun()
    else:
        _run_clicked = st.button("▶ 분석 실행", type="primary", use_container_width=True)

    # 파일 업로드
    uploaded = st.file_uploader(
        "📂 영상 파일", type=["mp4", "mov", "avi", "mkv", "m4v"],
        accept_multiple_files=True, label_visibility="visible",
    )

    if st.session_state.analysis_summary:
        st.success(st.session_state.analysis_summary)

    # 파라미터
    st.caption("⚙️ 분석 파라미터")
    threshold  = st.slider("모션 임계값 (낮을수록 민감)", 1, 200, cfg_base.motion.threshold, 1)
    sample_fps = st.slider("탐지 샘플 fps", 0.5, 5.0, cfg_base.detect.sample_fps, 0.5)
    conf       = st.slider("탐지 신뢰도", 0.1, 0.9, cfg_base.detect.conf, 0.05)
    frame_width = st.select_slider(
        "분석 해상도 (속도↑정밀↓)",
        options=[0, 160, 300, 480, 640],
        value=cfg_base.motion.frame_width if cfg_base.motion.frame_width in (0, 160, 300, 480, 640) else 300,
        format_func=lambda v: "원본" if v == 0 else f"{v}px",
    )
    min_area  = st.slider("최소 모션 영역 (px)", 5, 1000, cfg_base.motion.min_area, 5)
    merge_gap = st.slider("모션 병합 간격 (초)", 0, 120, int(cfg_base.motion.merge_gap_sec), 5)

cfg = override_config(cfg_base, threshold, sample_fps, conf, frame_width, min_area, float(merge_gap))

# 분석 실행 처리
if not st.session_state.analyzing and _run_clicked:
    targets: list[str] = []
    if uploaded:
        for uf in uploaded:
            dest = cfg.paths.uploads / uf.name
            dest.write_bytes(uf.getbuffer())
            targets.append(str(dest))
    if not targets:
        with ctrl_col:
            st.error("영상 파일을 업로드하세요.")
    else:
        st.session_state.pending_targets = targets
        st.session_state.analyzing = True
        st.session_state.analysis_done = False
        st.session_state.analysis_summary = ""
        st.session_state.analysis_state = {"progress": 0.0, "msg": "분석 준비 중…", "done": False}
        st.session_state.analysis_thread = None
        st.session_state.stop_event = None
        st.rerun()

# ── 우측 메인 영역 ──────────────────────────
with main_col:
    if st.session_state.analyzing:
        state: dict = st.session_state.analysis_state
        thread: threading.Thread | None = st.session_state.analysis_thread

        if thread is None or not thread.is_alive():
            if not state.get("done"):
                stop_ev = threading.Event()
                st.session_state.stop_event = stop_ev
                targets_snap = list(st.session_state.pending_targets)
                cfg_snap = cfg

                def _worker(_targets, _cfg, _state, _stop):
                    def on_progress(p, msg):
                        _state["progress"] = p
                        _state["msg"] = msg
                    total_clips = total_dets = total_raw = 0
                    try:
                        for t in _targets:
                            if _stop.is_set():
                                break
                            for r in process_folder(t, _cfg, progress_cb=on_progress, stop_event=_stop):
                                total_clips += r.n_clips
                                total_raw   += r.n_raw_clips
                                total_dets  += r.n_detections
                    except Exception as exc:
                        _state["error"] = str(exc)
                    _state["clips"] = total_clips
                    _state["raw_clips"] = total_raw
                    _state["dets"] = total_dets
                    _state["done"] = True

                t = threading.Thread(target=_worker,
                                     args=(targets_snap, cfg_snap, state, stop_ev), daemon=True)
                st.session_state.analysis_thread = t
                t.start()

        if state.get("done"):
            clips    = state.get("clips", 0)
            filtered = state.get("raw_clips", 0) - clips
            dets     = state.get("dets", 0)
            summary  = f"완료: 모션클립 {clips}건 (탐지 {dets}건)"
            if filtered:
                summary += f" / 노이즈 제거 {filtered}건"
            if "error" in state:
                summary = f"오류 발생: {state['error']}"
            st.session_state.analyzing = False
            st.session_state.analysis_done = True
            st.session_state.analysis_thread = None
            st.session_state.pending_targets = []
            st.session_state.analysis_summary = summary
            st.rerun()

        _, c, _ = st.columns([1, 4, 1])
        with c:
            st.markdown(_ANALYZING_HEADER, unsafe_allow_html=True)
            p   = float(state.get("progress", 0.0))
            msg = str(state.get("msg", "분석 준비 중…"))
            st.markdown(f"<div style='text-align:center;font-size:3rem;font-weight:900;"
                        f"color:#3b82f6;margin:0.3rem 0;'>{int(p * 100)}%</div>",
                        unsafe_allow_html=True)
            st.progress(min(p, 1.0))
            st.markdown(f"<div style='text-align:center;color:#94a3b8;font-size:0.9rem;"
                        f"margin-top:0.4rem;'>{msg}</div>", unsafe_allow_html=True)

        _time.sleep(0.4)
        st.rerun()

    elif not st.session_state.analysis_done:
        st.markdown(_LOGO_HTML, unsafe_allow_html=True)

    else:
        conn   = connect(cfg)
        videos = get_videos(conn)

        if not videos:
            st.info("분석된 영상이 없습니다.")
            conn.close()
        else:
            labels = {f"#{v['id']} {Path(v['path']).name}": v for v in videos}
            sel_label = st.selectbox("영상 선택", list(labels.keys()), label_visibility="collapsed")
            video = labels[sel_label]
            st.caption(f"📹 {Path(video['path']).name}  ·  {fmt_time(video['duration_sec'])}  ·  "
                       f"{video['width']}×{video['height']}  ·  {video['codec'].upper()}")

            events = get_events(conn, video["id"])
            if not events:
                st.warning("이 영상에서 YOLO가 확인한 모션 이벤트가 없습니다.\n\n"
                           "가능한 원인:\n- 사람·차량 미탐지 (classes: 0,2,3,5,7)\n"
                           f"- 신뢰도 너무 높음 (conf={cfg.detect.conf:.2f})\n"
                           "- 모션 임계값 너무 높음\n\n"
                           "`require_detection: false`로 YOLO 필터를 끌 수 있습니다.")
                conn.close()
            else:
                # ── 썸네일 그리드 ──
                THUMB_COLS = 5
                st.markdown(f"**모션 클립 {len(events)}개** — 클릭하면 재생합니다")
                for row in [events[i:i+THUMB_COLS] for i in range(0, len(events), THUMB_COLS)]:
                    cols = st.columns(len(row))
                    for col, ev in zip(cols, row):
                        idx    = events.index(ev)
                        is_sel = idx == st.session_state.selected_event_idx
                        thumb  = ev.get("thumbnail_path") if isinstance(ev, dict) else None
                        with col:
                            if thumb and Path(thumb).exists():
                                st.image(str(thumb), use_container_width=True, caption=None)
                            else:
                                st.markdown("<div style='background:#1e293b;height:80px;border-radius:4px;"
                                            "display:flex;align-items:center;justify-content:center;"
                                            "color:#475569;font-size:1.5rem;'>🎞️</div>",
                                            unsafe_allow_html=True)
                            if st.button(
                                f"{'▶ ' if is_sel else ''}움직임{idx+1:03d}\n"
                                f"{fmt_time(ev['start_sec'])}~{fmt_time(ev['end_sec'])}",
                                key=f"clip_btn_{idx}", use_container_width=True,
                                type="primary" if is_sel else "secondary",
                            ):
                                st.session_state.selected_event_idx = idx
                                st.rerun()

                st.divider()

                # ── 플레이어 ──
                sel_ev  = events[min(st.session_state.selected_event_idx, len(events)-1)]
                sel_idx = events.index(sel_ev)
                st.subheader(f"움직임{sel_idx+1:03d}  ·  "
                             f"{fmt_time(sel_ev['start_sec'])} ~ {fmt_time(sel_ev['end_sec'])}")

                play_col, det_col = st.columns([3, 1])
                with play_col:
                    orig = Path(video["path"])
                    if orig.exists():
                        st.video(str(orig), start_time=int(sel_ev["start_sec"]))
                        st.caption(f"▶ {fmt_time(sel_ev['start_sec'])} ~ "
                                   f"{fmt_time(sel_ev['end_sec'])} 구간 — 시작 위치에서 재생됩니다")
                    else:
                        st.warning("영상 파일을 찾을 수 없습니다.")

                with det_col:
                    dets = get_detections(conn, sel_ev["id"])
                    if dets:
                        rows_html = "".join(
                            f"<div style='padding:6px 0;border-bottom:1px solid #1e293b;'>"
                            f"<span style='background:#166534;color:#bbf7d0;padding:2px 7px;"
                            f"border-radius:4px;font-size:0.78rem;font-family:monospace;'>{d['class_name']}</span>"
                            f"<span style='color:#94a3b8;font-size:0.82rem;'> ×{d['n']}</span><br>"
                            f"<span style='color:#64748b;font-size:0.78rem;'>conf {d['conf']} @ {fmt_time(d['t_sec'])}</span>"
                            f"</div>"
                            for d in dets
                        )
                        st.markdown(
                            f"<div style='font-size:0.85rem;font-weight:600;color:#cbd5e1;"
                            f"margin-bottom:6px;'>탐지 객체 ({len(dets)}건)</div>"
                            f"<div style='height:420px;overflow-y:auto;border:1px solid #1e293b;"
                            f"border-radius:6px;padding:8px;'>{rows_html}</div>",
                            unsafe_allow_html=True,
                        )
                    else:
                        st.markdown("<div style='color:#64748b;font-size:0.9rem;margin-top:1rem;'>"
                                    "탐지 객체 없음</div>", unsafe_allow_html=True)

                conn.close()
