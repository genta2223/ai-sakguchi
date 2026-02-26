"""
app.py — Streamlit Cloud AI Avatar (与那国町議会議員 阪口源太)
Main application: WebM video avatar + Cloud TTS + Gemini RAG + YouTube chat.
"""
import os
import streamlit as st

# 🚀 Streamlitがstaticフォルダを正しく認識するためのハック
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent))

# 🚀 どんなスレッドからでも参照できるよう、OSの環境変数にキーを強制セット
if "GEMINI_API_KEY" in st.secrets:
    os.environ["GOOGLE_API_KEY"] = st.secrets["GEMINI_API_KEY"]
if "GOOGLE_API_KEY" in st.secrets:
    os.environ["GOOGLE_API_KEY"] = st.secrets["GOOGLE_API_KEY"]

import logging
import time
import threading
import json
import hashlib
import uuid
from queue import Queue, Empty

from streamlit_autorefresh import st_autorefresh
import shutil

from youtube_monitor import ChatItem, start_youtube_monitor

# --- Modular Imports ---
from core_paths import PathManager, LOCAL_STATIC_DIR
from core_ai_worker import init_worker

# ============================================================
# Configuration
# ============================================================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

st.set_page_config(
    page_title="AI阪口源太 - 与那国町議会議員",
    page_icon="🏝️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ============================================================
# Hide Streamlit UI elements for clean OBS capture
# ============================================================
query_params = st.query_params
is_embed = query_params.get("embed", "0") == "1"

hide_css = """
<style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .stDeployButton {display: none;}
    /* Remove default padding for fullscreen feel */
    .block-container {
        padding-top: 0.5rem;
        padding-bottom: 0;
        padding-left: 1rem;
        padding-right: 1rem;
    }
    /* Make iframe take full width */
    iframe {
        width: 100% !important;
    }
</style>
"""
st.markdown(hide_css, unsafe_allow_html=True)

if is_embed:
    # Extra CSS to hide EVERYTHING except the avatar
    st.markdown("""
    <style>
        .stTextInput, .stButton, [data-testid="stBottom"] {
            display: none !important;
        }
    </style>
    """, unsafe_allow_html=True)


# ============================================================
# Session State Initialization
# ============================================================
if "queue" not in st.session_state:
    st.session_state.queue = Queue()

if "processing" not in st.session_state:
    st.session_state.processing = False
if "last_proc_start" not in st.session_state:
    st.session_state.last_proc_start = 0.0
if "progress_msg" not in st.session_state:
    st.session_state.progress_msg = "Ready"

if "current_audio" not in st.session_state:
    st.session_state.current_audio = None  # {audio_b64, emotion, response_text}

if "history" not in st.session_state:
    st.session_state.history = []  # List of (question, response, emotion)

if "yt_thread" not in st.session_state:
    st.session_state.yt_thread = None
    st.session_state.yt_stop = None

if "output_queue" not in st.session_state:
    st.session_state.output_queue = Queue()

if "worker_thread" not in st.session_state:
    st.session_state.worker_thread = None
    st.session_state.worker_stop = None

if "has_greeted" not in st.session_state:
    st.session_state.has_greeted = False

if "avatar_placeholder" not in st.session_state:
    st.session_state.avatar_placeholder = None

if "started" not in st.session_state:
    st.session_state.started = False

if "current_avatar_task" not in st.session_state:
    st.session_state.current_avatar_task = None


# ============================================================
# YouTube Monitor (start once)
# ============================================================
def init_youtube_monitor():
    """Start YouTube monitor if enabled and not already running."""
    enable = st.secrets.get("ENABLE_YOUTUBE_MONITOR", False)
    video_id = st.secrets.get("YT_ID", "")

    if enable and video_id and st.session_state.yt_thread is None:
        thread, stop_event = start_youtube_monitor(video_id, st.session_state.queue)
        st.session_state.yt_thread = thread
        st.session_state.yt_stop = stop_event
        logger.info("[App] YouTube monitor started.")


# ============================================================
# Startup Greeting
# ============================================================
def queue_startup_greeting():
    """Queue the opening message on first run."""
    if not st.session_state.has_greeted:
        st.session_state.has_greeted = True
        logger.info("[App] Queuing startup greeting.")
        item = ChatItem(
            message_text="（System: 配信開始の挨拶をしてください。「与那国町議会議員の阪口源太です。町民のみなさんのご質問にお答えします」と言ってください）",
            author_name="System",
            source="system",
        )
        st.session_state.queue.put(item)


# ============================================================
# Process Queue Handlers
# ============================================================
def poll_results(placeholder, session_id: str):
    """Checks the output queue for finished tasks."""
    try:
        while True:
            res = st.session_state.output_queue.get_nowait()
            if res["type"] == "progress":
                st.session_state.progress_msg = res["msg"]
                st.session_state.processing = True
            elif res["type"] == "result":
                # Robust Task ID: time + hash of text
                text_hash = hashlib.md5(res["response_text"].encode("utf-8")).hexdigest()[:8]
                task_id = f"{time.time()}_{text_hash}"

                task_data = {
                    "task_id": task_id,
                    "audio_b64": res["audio_b64"],
                    "emotion": res["emotion"],
                    "response_text": res["response_text"],
                    "is_initial_greeting": res.get("is_initial_greeting", False)
                }
                
                # 🚀 In-Memory State: Store directly in session state instead of writing to file
                st.session_state.current_avatar_task = task_data
                logger.info(f"[App] Updated in-memory task: {task_id}")
                
                if res.get("is_initial_greeting"):
                    # Cache greeting task data in session state for other users/sessions if needed,
                    st.session_state.greeting_task_cache = task_data
                    
                    # 🚀 物理ファイルにも永続保存 (再起動後の爆速起動のため)
                    try:
                        cache_file = LOCAL_STATIC_DIR / "greeting_cache.json"
                        with open(cache_file, "w", encoding="utf-8") as f:
                            json.dump(task_data, f, ensure_ascii=False, indent=2)
                        logger.info(f"[Cache] Saved initial greeting to physical file: {cache_file.name}")
                    except Exception as e:
                        logger.warning(f"[Cache] Failed to save to physical file: {e}")

                # Still update history for UI
                st.session_state.history.append({
                    "question": res["question"],
                    "author": res["author"],
                    "response": res["response_text"],
                    "emotion": res["emotion"],
                })
                if len(st.session_state.history) > 20:
                    st.session_state.history = st.session_state.history[-20:]
                
                st.session_state.processing = False
                st.session_state.progress_msg = "Ready"
                # NO st.rerun() HERE - let the next auto-refresh update the UI 
                # to prevent interrupting the JS execution that just started polling.
            
            elif res["type"] == "error":
                with placeholder:
                    st.error(f"Processing Error: {res['msg']}")
                st.session_state.processing = False
                st.session_state.progress_msg = "Error occurred"
    except Empty:
        pass


# ============================================================
# Render Avatar Component
# ============================================================
def render_avatar(placeholder, session_id: str):
    """Render the avatar using direct HTML injection with Hybrid Delivery (URL Videos + In-Memory Tasks)."""
    try:
        html_path = LOCAL_STATIC_DIR / "avatar.html"
        if html_path.exists():
            html_content = html_path.read_text(encoding="utf-8")
            
            # 1. 🚀 WebM動画のBase64エンコードマップを取得 (Streamlit Cloudのパス問題回避のため直埋め込み)
            video_urls = PathManager.get_video_base64_map()
            
            # 2. 🚀 現在のタスクデータを取得 (TTS音声は引き続きインメモリで即時受け渡し)
            task_data = st.session_state.get("current_avatar_task")
            
            # 3. 🚀 データをHTMLに注入
            app_data_json = json.dumps({
                "video_urls": video_urls,
                "task": task_data,
                "sid": session_id,
                "buster": time.time()
            })
            
            injection = f"""
            <script>
                window.AVATAR_APP_DATA = {app_data_json};
            </script>
            """
            final_html = html_content.replace("<head>", f"<head>{injection}")
            
            with placeholder:
                st.components.v1.html(final_html, height=600, scrolling=False)
        else:
            with placeholder:
                st.error("avatar.html not found.")
    except Exception as e:
        logger.error(f"Failed to render avatar: {e}")
        with placeholder:
            st.error(f"Render Error: {e}")


# ============================================================
# Main UI Layout
# ============================================================
# def ensure_static_deployment():
#     """Wrapper for PathManager's safe deployment."""
#     return PathManager.get_internal_static() or LOCAL_STATIC_DIR

def cleanup_stale_tasks():
    """Remove session task files older than 1 hour from Local Static."""
    try:
        now = time.time()
        for f in LOCAL_STATIC_DIR.glob("task_*.json"):
            if now - f.stat().st_mtime > 3600:
                f.unlink()
                logger.info(f"[Cleanup] Removed stale task file: {f.name}")
    except Exception as e:
        logger.warning(f"[Cleanup] Failed: {e}")

def main():
    logger.info(f"[App] Starting AI Avatar App (Multi-User v19.2)")
    
    # Initialize Session ID
    if "session_id" not in st.session_state:
        st.session_state.session_id = str(uuid.uuid4())[:8]
    
    sid = st.session_state.session_id

    # Periodic Cleanup
    if "last_cleanup" not in st.session_state or time.time() - st.session_state.last_cleanup > 600:
        cleanup_stale_tasks()
        st.session_state.last_cleanup = time.time()

    # 🚀 Ghost Cleaning is now disabled in favor of In-Memory Media Injection
    if "deployment_done" not in st.session_state:
        # We still call it but it now just returns the local path as a dummy
        PathManager.ensure_safe_deployment()
        st.session_state.deployment_done = True
        logger.info(f"[App] In-memory mode active (Filesystem reset skipped)")

    # Auto-refresh every 60 seconds (Heartbeat only)
    st_autorefresh(interval=60000, limit=None, key="auto_refresh")

    # Initialize services
    init_youtube_monitor()
    init_worker()  # Start the AI-processing background thread

    # Trigger Initial Greeting
    if "greeting_queued" not in st.session_state:
        st.session_state.greeting_queued = True
        
        # 1. Level 1 (RAM): セッション内キャッシュをチェック
        if "greeting_task_cache" in st.session_state:
            st.session_state.current_avatar_task = st.session_state.greeting_task_cache
            logger.info(f"[Cache] RAM HIT! Serving greeting from session state.")
        else:
            # 2. Level 2 (Disk): 物理キャッシュファイルをチェック
            cache_file = LOCAL_STATIC_DIR / "greeting_cache.json"
            if cache_file.exists():
                try:
                    with open(cache_file, "r", encoding="utf-8") as f:
                        cached_data = json.load(f)
                    st.session_state.greeting_task_cache = cached_data
                    st.session_state.current_avatar_task = cached_data
                    logger.info(f"[Cache] DISK HIT! Loaded greeting from {cache_file.name}")
                except Exception as e:
                    logger.warning(f"[Cache] Failed to load disk cache: {e}")
                    # Fallback to level 3 if load fails
                    pass
            
            # 3. Level 3 (Gemini): どちらもなければ新規生成を依頼
            if "current_avatar_task" not in st.session_state or st.session_state.current_avatar_task is None:
                logger.info(f"[Cache] MISS! Queuing initial greeting generation via Gemini.")
                item = ChatItem(
                    message_text="与那国島の町民の皆さんに自己紹介と、これからの島への想いを短く話してから、質問を募集してください。",
                    author_name="システム",
                    source="system",
                    is_initial_greeting=True
                )
                st.session_state.queue.put(item)

    # --- Avatar Area (top) ---
    avatar_container = st.empty()

    # polling status (pass container for error display)
    poll_results(avatar_container, sid)

    render_avatar(avatar_container, sid)
    
    # Mark as started so subsequent reruns (heartbeat or full) include the flag
    st.session_state.started = True

    # --- Processing indicator / Queue status ---
    if st.session_state.processing:
        # Show queue transparency
        q_size = st.session_state.queue.qsize()
        if q_size > 0:
            st.warning(f"現在、他の町民の方の質問に回答中です。（あと {q_size} 人待ち）")
        
        st.info(f"AI阪口源太が考え中... ({st.session_state.progress_msg})")
        if st.button("強制リセット (停止した場合)", key="force_reset"):
            # Clear everything
            st.session_state.processing = False
            st.session_state.current_audio = None
            st.session_state.progress_msg = "Reset"
            st.session_state.started = False
            # Clear queues (re-init)
            st.session_state.queue = Queue()
            st.session_state.output_queue = Queue()
            st.toast("処理をリセットしました")
            # Inject JS to clear localStorage if possible
            st.components.v1.html("<script>localStorage.clear(); window.parent.location.reload();</script>", height=0)
            st.rerun()

    # --- Input and History Area (Fragmented) ---
    @st.fragment
    def chat_area():
        if not is_embed:
            st.markdown("---")
            cols = st.columns([6, 1])
            with cols[0]:
                user_input = st.text_input(
                    "💬 質問を入力",
                    placeholder="与那国島の未来について教えてください...",
                    key="user_input_field", 
                    label_visibility="collapsed",
                )
            with cols[1]:
                send_pressed = st.button("送信", type="primary", use_container_width=True)

            if send_pressed and user_input:
                logger.info(f"[Input] User submitted: {user_input[:20]}")
                
                # 🚀 考え中フラグを即座にセット (JS側で talking_wait.webm を再生させる)
                st.session_state.current_avatar_task = {"task_id": "waiting", "audio_b64": None}
                logger.info(f"[Input] Set 'waiting' state for avatar.")

                item = ChatItem(
                    message_text=user_input,
                    author_name="町民",
                    source="direct",
                )
                st.session_state.queue.put(item)
                st.toast("質問を受け付けました。順番に回答します。")
                
                # 🚀 アバターの状態をHTMLに即時反映させるため、アプリをリラン
                st.rerun()

            # --- Response History (compact) ---
            if st.session_state.history:
                with st.expander(f"📜 応答履歴 ({len(st.session_state.history)}件)", expanded=False):
                    for entry in reversed(st.session_state.history):
                        st.markdown(
                            f"**Q ({entry['author']}):** {entry['question'][:80]}  \n"
                            f"**A [{entry['emotion']}]:** {entry['response']}"
                        )
                        st.divider()

    chat_area()

if __name__ == "__main__":
    main()