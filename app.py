"""
app.py — Streamlit Cloud AI Avatar (与那国町議会議員 阪口源太)
Main application: WebM video avatar + Cloud TTS + Gemini RAG + YouTube chat.
"""
import base64
import logging
import time
from pathlib import Path
from queue import Queue, Empty

import streamlit as st
from streamlit_autorefresh import st_autorefresh

from brain import generate_response
from tts import synthesize_speech
from youtube_monitor import ChatItem, start_youtube_monitor

# ============================================================
# Configuration
# ============================================================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

APP_DIR = Path(__file__).parent
VIDEOS_DIR = APP_DIR / "videos"
COMPONENT_HTML = APP_DIR / "avatar_component.html"

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
    iframe[title="streamlit_app.avatar_component"] {
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

if "current_audio" not in st.session_state:
    st.session_state.current_audio = None  # {audio_b64, emotion, response_text}

if "history" not in st.session_state:
    st.session_state.history = []  # List of (question, response, emotion)

if "yt_thread" not in st.session_state:
    st.session_state.yt_thread = None
    st.session_state.yt_stop = None

if "startup_done" not in st.session_state:
    st.session_state.startup_done = False


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
    if not st.session_state.startup_done:
        st.session_state.startup_done = True
        item = ChatItem(
            message_text="（System: 配信開始の挨拶をしてください。「与那国町議会議員の阪口源太です。町民のみなさんのご質問にお答えします」と言ってください）",
            author_name="System",
            source="system",
        )
        st.session_state.queue.put(item)


# ============================================================
# Process Queue
# ============================================================
def process_next_item():
    """Process one item from the queue: Gemini → TTS → set audio state."""
    if st.session_state.processing:
        return
    if st.session_state.current_audio is not None:
        return  # Still playing

    try:
        item: ChatItem = st.session_state.queue.get_nowait()
    except Empty:
        return

    st.session_state.processing = True
    logger.info(f"[Process] {item.author_name}: {item.message_text[:30]}...")

    try:
        # 1. Generate response
        reply_text, emotion = generate_response(item.message_text)
        logger.info(f"[Process] Reply: {reply_text[:40]}... Emotion: {emotion}")

        # 2. Generate TTS audio (base64)
        audio_b64 = synthesize_speech(reply_text)
        logger.info(f"[Process] TTS OK: {len(audio_b64)} chars b64")

        # 3. Set current audio for the component
        st.session_state.current_audio = {
            "audio_b64": audio_b64,
            "emotion": emotion,
            "response_text": reply_text,
        }

        # 4. Add to history
        st.session_state.history.append({
            "question": item.message_text if item.source != "system" else "(起動挨拶)",
            "author": item.author_name,
            "response": reply_text,
            "emotion": emotion,
        })
        # Keep last 20
        if len(st.session_state.history) > 20:
            st.session_state.history = st.session_state.history[-20:]

    except Exception as e:
        logger.error(f"[Process] Error: {e}", exc_info=True)

    st.session_state.processing = False


# ============================================================
# Video Source Encoding
# ============================================================
@st.cache_data
def get_video_b64(filename: str) -> str:
    """Read a video file and return base64 data URI."""
    path = VIDEOS_DIR / filename
    if not path.exists():
        return ""
    data = path.read_bytes()
    b64 = base64.b64encode(data).decode("utf-8")
    return f"data:video/webm;base64,{b64}"


# ============================================================
# Render Avatar Component
# ============================================================
def render_avatar():
    """Render the HTML5 video avatar component with current audio data."""
    html_template = COMPONENT_HTML.read_text(encoding="utf-8")

    # Inject video sources
    idle_src = get_video_b64("idle_blink.webm")
    normal_src = get_video_b64("talking_normal.webm")
    strong_src = get_video_b64("talking_strong.webm")

    html = html_template.replace("__IDLE_SRC__", idle_src)
    html = html.replace("__NORMAL_SRC__", normal_src)
    html = html.replace("__STRONG_SRC__", strong_src)

    # If there's audio to play, inject a postMessage call
    audio_data = st.session_state.current_audio
    if audio_data:
        inject_script = f"""
        <script>
            setTimeout(() => {{
                window.postMessage({{
                    type: 'avatar_command',
                    action: 'play_audio',
                    audio_b64: '{audio_data["audio_b64"]}',
                    emotion: '{audio_data["emotion"]}',
                    response_text: `{audio_data["response_text"].replace('`', "'")}`
                }}, '*');
            }}, 500);
        </script>
        """
        html += inject_script
        # Clear after injecting (will play once)
        st.session_state.current_audio = None

    st.components.v1.html(html, height=600, scrolling=False)


# ============================================================
# Main UI Layout
# ============================================================
def main():
    # Auto-refresh every 3 seconds to poll queue
    st_autorefresh(interval=3000, limit=None, key="auto_refresh")

    # Initialize services
    init_youtube_monitor()
    queue_startup_greeting()

    # Process any pending items
    process_next_item()

    # --- Avatar Area (top) ---
    render_avatar()

    # --- Input Area (bottom) ---
    if not is_embed:
        st.markdown("---")
        cols = st.columns([6, 1])
        with cols[0]:
            user_input = st.text_input(
                "💬 質問を入力",
                placeholder="与那国島の未来について教えてください...",
                key="user_input",
                label_visibility="collapsed",
            )
        with cols[1]:
            send_pressed = st.button("送信", type="primary", use_container_width=True)

        if send_pressed and user_input:
            item = ChatItem(
                message_text=user_input,
                author_name="阪口源太",
                source="direct",
            )
            st.session_state.queue.put(item)
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


if __name__ == "__main__":
    main()
