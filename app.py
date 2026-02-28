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
import smtplib
from email.mime.text import MIMEText
from queue import Queue, Empty

from streamlit_autorefresh import st_autorefresh

from youtube_monitor import ChatItem, start_youtube_monitor

# --- Modular Imports ---
from core_paths import PathManager, LOCAL_STATIC_DIR
from core_ai_worker import init_worker

# 🚀 モジュールレベルキャッシュ: 動画Base64マップを一度だけ生成し、全rerunsで再利用
# (session_stateに入れるとOOM、毎回読み直すとHTMLが変わるかもしれない)
_VIDEO_B64_CACHE = None
_HTML_TEMPLATE_CACHE = None

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

if "history" not in st.session_state:
    st.session_state.history = []

if "yt_thread" not in st.session_state:
    st.session_state.yt_thread = None
    st.session_state.yt_stop = None

if "output_queue" not in st.session_state:
    st.session_state.output_queue = Queue()

if "worker_thread" not in st.session_state:
    st.session_state.worker_thread = None
    st.session_state.worker_stop = None

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
# Process Queue Handlers
# ============================================================
def poll_results(session_id: str) -> bool:
    """Checks the output queue for finished tasks. Returns True if a new result was found."""
    found_result = False
    try:
        while True:
            res = st.session_state.output_queue.get_nowait()
            if res["type"] == "progress":
                st.session_state.progress_msg = res["msg"]
                st.session_state.processing = True
            elif res["type"] == "result":
                text_hash = hashlib.md5(res["response_text"].encode("utf-8")).hexdigest()[:8]
                task_id = f"{time.time()}_{text_hash}"

                task_data = {
                    "task_id": task_id,
                    "audio_b64": res["audio_b64"],
                    "emotion": res["emotion"],
                    "response_text": res["response_text"],
                    "is_initial_greeting": res.get("is_initial_greeting", False)
                }
                
                st.session_state.current_avatar_task = task_data
                logger.info(f"[App] Updated in-memory task: {task_id}")
                
                if res.get("is_initial_greeting"):
                    st.session_state.greeting_task_cache = task_data
                    try:
                        cache_file = LOCAL_STATIC_DIR / "greeting_cache.json"
                        with open(cache_file, "w", encoding="utf-8") as f:
                            json.dump(task_data, f, ensure_ascii=False, indent=2)
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
                st.session_state.processing = False
                st.session_state.progress_msg = f"Error: {res['msg']}"
    except Empty:
        pass
    return found_result


# ============================================================
# Render Avatar Component
# ============================================================
def render_avatar(session_id: str):
    """Render the avatar directly (NOT inside st.empty) so Streamlit preserves the iframe across reruns."""
    try:
        html_path = LOCAL_STATIC_DIR / "avatar.html"
        if html_path.exists():
            # HTMLテンプレートもモジュールレベルでキャッシュ
            global _VIDEO_B64_CACHE, _HTML_TEMPLATE_CACHE
            if _VIDEO_B64_CACHE is None:
                _VIDEO_B64_CACHE = PathManager.get_video_base64_map()
            if _HTML_TEMPLATE_CACHE is None:
                _HTML_TEMPLATE_CACHE = html_path.read_text(encoding="utf-8")
            
            video_urls = _VIDEO_B64_CACHE
            html_content = _HTML_TEMPLATE_CACHE
            task_data = st.session_state.get("current_avatar_task")
            
            # buster = task_id: タスクが変わった時だけHTMLが変わる → iframeが再生成される
            task_id = task_data.get("task_id", "idle") if task_data else "idle"
            app_data_json = json.dumps({
                "video_urls": video_urls,
                "task": task_data,
                "sid": session_id,
                "buster": task_id
            })
            
            injection = f"""
            <script>
                window.AVATAR_APP_DATA = {app_data_json};
            </script>
            """
            final_html = html_content.replace("<head>", f"<head>{injection}")
            
            # ★ 核心: st.empty()を使わず直接描画 → Streamlitがハッシュ比較でiframeを保持
            st.components.v1.html(final_html, height=600, scrolling=False)
        else:
            st.error("avatar.html not found.")
    except Exception as e:
        logger.error(f"Failed to render avatar: {e}")
        st.error(f"Render Error: {e}")



def main():
    logger.info(f"[App] Starting AI Avatar App (v20.0 Stable)")
    
    # Initialize Session ID
    if "session_id" not in st.session_state:
        st.session_state.session_id = str(uuid.uuid4())[:8]
    
    sid = st.session_state.session_id

    if "deployment_done" not in st.session_state:
        PathManager.ensure_safe_deployment()
        st.session_state.deployment_done = True

    # 固定5秒ポーリング (動的切り替えはCloudでコンポーネントリセットループを起こすため廃止)
    st_autorefresh(interval=5000, limit=None, key="auto_refresh")

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

    # ポーリング → 結果をsession_stateに反映
    poll_results(sid)

    # ★ 核心: st.empty()を使わず直接描画し、iframeの再生成を防ぐ
    render_avatar(sid)

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
            st.session_state.progress_msg = "Reset"
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

    # --- Direct Email Form (Bottom) ---
    st.markdown("---")
    with st.expander("✉️ AIで解決しない場合は、阪口源太に直接質問する"):
        with st.form(key="direct_email_form", clear_on_submit=True):
            reply_email = st.text_input("📧 返信用メールアドレス", placeholder="example@email.com")
            user_message = st.text_area("💬 質問・メッセージ内容", placeholder="AIでは解決できなかった具体的なご質問をどうぞ...", height=120)
            submitted = st.form_submit_button("📨 阪口源太に送信する")

            if submitted:
                if not reply_email or not user_message:
                    st.warning("メールアドレスとメッセージの両方を入力してください。")
                else:
                    success = send_direct_message(reply_email, user_message)
                    if success:
                        st.success("✅ 阪口源太本人にメッセージを送信しました！")
                    else:
                        st.error("❌ 送信に失敗しました。しばらく待ってからもう一度お試しください。")


def send_direct_message(reply_email: str, user_message: str) -> bool:
    """Send a direct message to the politician via Gmail SMTP. Returns True on success."""
    try:
        gmail_user = st.secrets.get("GMAIL_USER", "")
        gmail_pass = st.secrets.get("GMAIL_APP_PASSWORD", "")
        target_email = st.secrets.get("TARGET_EMAIL", "")

        if not gmail_user or not gmail_pass or not target_email:
            logger.error("[Email] Missing GMAIL_USER, GMAIL_APP_PASSWORD, or TARGET_EMAIL in secrets.")
            return False

        # 1. Build conversation history
        history_text = "（履歴なし）"
        if st.session_state.history:
            lines = []
            for entry in st.session_state.history:
                lines.append(f"Q ({entry['author']}): {entry['question']}")
                lines.append(f"A [{entry['emotion']}]: {entry['response']}")
                lines.append("")
            history_text = "\n".join(lines)

        # 2. Build extra cache report
        extra_report = "（なし）"
        try:
            extra_cache_file = LOCAL_STATIC_DIR / "extra_cache.json"
            if extra_cache_file.exists():
                with open(extra_cache_file, "r", encoding="utf-8") as f:
                    extra_data = json.load(f)
                if extra_data:
                    report_lines = []
                    for i, item in enumerate(extra_data, 1):
                        q = item.get("question", "N/A")
                        a = item.get("response_text", "N/A")[:200]
                        report_lines.append(f"{i}. Q: {q}\n   A: {a}")
                    extra_report = "\n".join(report_lines)
        except Exception as e:
            logger.warning(f"[Email] Failed to read extra_cache: {e}")

        # 3. Compose email body
        body = (
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"【ユーザーからのメッセージ】\n"
            f"{user_message}\n\n"
            f"【返信用アドレス】\n"
            f"{reply_email}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"【これまでの会話ログ】\n"
            f"{history_text}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"【システム報告：新着の未回答ログ (extra_cache)】\n"
            f"{extra_report}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        )

        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = "【町民より】AIアバター経由での直接質問"
        msg["From"] = gmail_user
        msg["To"] = target_email

        # 4. Send via Gmail SMTP
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_user, gmail_pass)
            server.sendmail(gmail_user, target_email, msg.as_string())

        logger.info(f"[Email] Successfully sent direct message from {reply_email}")

        # 5. Reset extra_cache.json after successful send (serves as admin report delivery)
        try:
            extra_cache_file = LOCAL_STATIC_DIR / "extra_cache.json"
            with open(extra_cache_file, "w", encoding="utf-8") as f:
                json.dump([], f)
            logger.info("[Email] extra_cache.json reset after report delivery.")
        except Exception as e:
            logger.warning(f"[Email] Failed to reset extra_cache: {e}")

        return True

    except Exception as e:
        logger.error(f"[Email] Failed to send: {e}")
        return False


if __name__ == "__main__":
    main()