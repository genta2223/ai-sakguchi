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
    initial_sidebar_state="expanded",
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
def poll_results(placeholder, session_id: str) -> bool:
    """Checks the output queue for finished tasks. Returns True if a new result was found."""
    found_result = False
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

                task_data_full = {
                    "task_id": task_id,
                    "audio_b64": res["audio_b64"],
                    "emotion": res["emotion"],
                    "response_text": res["response_text"],
                    "is_initial_greeting": res.get("is_initial_greeting", False)
                }
                
                # 🚀 物理ファイルへフルデータを保存 (フロントのJSが非同期でフェッチする)
                try:
                    task_file = LOCAL_STATIC_DIR / f"task_{task_id}.json"
                    with open(task_file, "w", encoding="utf-8") as f:
                        json.dump(task_data_full, f, ensure_ascii=False)
                except Exception as e:
                    logger.warning(f"[App] Failed to write heavy task file: {e}")

                # 🚀 Streamlitのsession_stateには軽量な参照(ID)だけを渡す
                task_data_light = {
                    "task_id": task_id,
                    "emotion": res["emotion"],
                    "response_text": res["response_text"],
                    "is_initial_greeting": res.get("is_initial_greeting", False)
                }
                
                st.session_state.current_avatar_task = task_data_light
                logger.info(f"[App] Updated light in-memory task: {task_id}")
                
                if res.get("is_initial_greeting"):
                    st.session_state.greeting_task_cache = task_data_full
                    try:
                        cache_file = LOCAL_STATIC_DIR / "greeting_cache.json"
                        with open(cache_file, "w", encoding="utf-8") as f:
                            json.dump(task_data_full, f, ensure_ascii=False, indent=2)
                        logger.info(f"[Cache] Saved initial greeting to physical file: {cache_file.name}")
                    except Exception as e:
                        logger.warning(f"[Cache] Failed to save to physical file: {e}")

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
                found_result = True
            
            elif res["type"] == "error":
                with placeholder:
                    st.error(f"Processing Error: {res['msg']}")
                st.session_state.processing = False
                st.session_state.progress_msg = "Error occurred"
    except Empty:
        pass
    return found_result


# ============================================================
# Render Avatar Component
# ============================================================
def render_avatar(placeholder, session_id: str):
    """Render the avatar using direct HTML injection with Hybrid Delivery (URL Videos + In-Memory Tasks)."""
    try:
        html_path = LOCAL_STATIC_DIR / "avatar.html"
        if html_path.exists():
            html_content = html_path.read_text(encoding="utf-8")
            
            # 1. 🚀 動画Base64マップをセッションキャッシュ (毎回4本のWebMを再エンコードしない = 数秒短縮)
            if "_video_b64_cache" not in st.session_state:
                st.session_state._video_b64_cache = PathManager.get_video_base64_map()
            video_urls = st.session_state._video_b64_cache
            
            # 2. 🚀 現在のタスクデータを取得 (軽量参照のみ)
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

# load_all_caches function # Moved inside main()
# find_in_cache function # Moved inside main()

# ============================================================
# API Endpoint Mode (Vercel Backend Hack)
# ============================================================
api_query = st.query_params.get("api_query")
if api_query:
    import json
    import base64
    from core_ai_worker import normalize_text, generate_response
    from tts import synthesize_speech
    
    # Simple caching layer copy for the API
    cache_combined = []
    try:
        if (LOCAL_STATIC_DIR / "faq_cache.json").exists():
            with open(LOCAL_STATIC_DIR / "faq_cache.json", "r", encoding="utf-8") as f:
                d = json.load(f)
                if isinstance(d, list): cache_combined.extend(d)
        if (LOCAL_STATIC_DIR / "extra_cache.json").exists():
            with open(LOCAL_STATIC_DIR / "extra_cache.json", "r", encoding="utf-8") as f:
                d_ext = json.load(f)
                if isinstance(d_ext, list): cache_combined.extend(d_ext)
    except:
        pass

    match = None
    norm_q = normalize_text(api_query)
    for item in cache_combined:
        try:
            if "question" in item and "response_text" in item:
                if normalize_text(str(item["question"])) == norm_q:
                    match = item
                    break
        except:
            pass

    try:
        if match:
            response_text = str(match["response_text"])
            emotion = str(match.get("emotion", "normal")).lower()
            audio_b64 = match.get("audio_b64", "")
        else:
            api_key = st.secrets.get("FINAL_MASTER_KEY") or st.secrets.get("GOOGLE_API_KEY") or ""
            c_json = st.secrets.get("GOOGLE_APPLICATION_CREDENTIALS_JSON") or ""
            p_key = st.secrets.get("GCP_PRIVATE_KEY") or ""
            c_email = st.secrets.get("GCP_CLIENT_EMAIL") or ""
            
            response_text, emotion = generate_response(api_query, api_key=api_key, use_cache=False)
            audio_b64 = synthesize_speech(response_text, creds_json=c_json, private_key=p_key, client_email=c_email, use_cache=False)
            
        emotion = emotion.lower()
        video_filename = "talking_normal.webm"
        if "idle" in emotion: video_filename = "idle_blink.webm"
        elif "strong" in emotion: video_filename = "talking_strong.webm"
        elif "wait" in emotion: video_filename = "talking_wait.webm"
        
        output = {
            "status": "success",
            "response_text": response_text,
            "emotion": emotion,
            "video_filename": video_filename,
            "audio_b64": audio_b64
        }
    except Exception as e:
        output = {"status": "error", "message": str(e)}

    # Send data marked clearly for the JavaScript regex extractor, skipping frontend render
    st.write(f"[[V_API_START]]{json.dumps(output)}[[V_API_END]]")
    st.stop()


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

    # 🚀 動的ポーリング: 処理中は2秒間隔で画面更新、アイドル時は60秒
    refresh_interval = 2000 if st.session_state.get("processing", False) else 60000
    st_autorefresh(interval=refresh_interval, limit=None, key="auto_refresh")

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

    # 🚀 ポーリング→結果発見→即座にst.rerun()で画面を更新
    got_result = poll_results(avatar_container, sid)

    render_avatar(avatar_container, sid)
    
    # 🚀 結果が見つかった場合、即座に再描画して最新のアバター状態を反映
    if got_result:
        st.rerun()
    
    # Mark as started so subsequent reruns (heartbeat or full) include the flag
    st.session_state.started = True

    # --- Input Area (Fragmented) ---
    @st.fragment
    def chat_area():
        if not is_embed:
            st.markdown("---")
            if st.session_state.get("processing", False):
                st.chat_input("💭 質問を入力 (今は考え中です...)", disabled=True)
            else:
                user_input = st.chat_input("💬 質問を入力 (例: 与那国島の未来について教えてください...)")

                if user_input:
                    logger.info(f"[Input] User submitted: {user_input[:20]}")
                    
                    # 🚀 連続送信防ぐため即座にprocessingをTrueにし、ロック
                    st.session_state.processing = True
                    
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
                    st.rerun()

    chat_area()

    # --- Status and History Area (Bottom) ---
    st.markdown("---")
    st.header("📜 応答履歴とステータス")
    if st.session_state.processing:
        q_size = st.session_state.queue.qsize()
        if q_size > 0:
            st.warning(f"現在、他の町民の方の質問に回答中です。（あと {q_size} 人待ち）")
        
        st.info(f"AI阪口源太が考え中... ({st.session_state.progress_msg})")
        if st.button("強制リセット (停止した場合)", key="history_force_reset"):
            st.session_state.processing = False
            st.session_state.current_audio = None
            st.session_state.progress_msg = "Reset"
            st.session_state.started = False
            st.session_state.queue = Queue()
            st.session_state.output_queue = Queue()
            st.toast("処理をリセットしました")
            st.components.v1.html("<script>localStorage.clear(); window.parent.location.reload();</script>", height=0)
            st.rerun()
            
    if st.session_state.history:
        for entry in reversed(st.session_state.history):
            st.markdown(
                f"**Q ({entry['author']}):** {entry['question'][:80]}  \n"
                f"**A [{entry['emotion']}]:** {entry['response']}"
            )
            st.divider()

if __name__ == "__main__":
    main()