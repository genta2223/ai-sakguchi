import os
import sys
from pathlib import Path

# 🚀 Streamlitがstaticフォルダを正しく認識するためのハック
sys.path.append(str(Path(__file__).parent))

import streamlit as st
# import json # Moved inside main()
# import logging # Moved inside main()
# import base64 # Moved inside main()

from core_paths import LOCAL_STATIC_DIR, PathManager
# from core_ai_worker import normalize_text, generate_response # Moved inside main()
# from tts import synthesize_speech # Moved inside main()

# logging.basicConfig(level=logging.INFO) # Moved inside main()
# logger = logging.getLogger(__name__) # Moved inside main()

st.set_page_config(
    page_title="AI阪口源太 - 与那国町議会議員",
    page_icon="🏝️",
    layout="wide",
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
    .block-container {
        padding-top: 0.5rem;
        padding-bottom: 0;
        padding-left: 1rem;
        padding-right: 1rem;
    }
</style>
"""
st.markdown(hide_css, unsafe_allow_html=True)

if is_embed:
    st.markdown("""
    <style>
        .stTextInput, .stButton, [data-testid="stBottom"] {
            display: none !important;
        }
    </style>
    """, unsafe_allow_html=True)

# OS環境変数の注入
if "GEMINI_API_KEY" in st.secrets:
    os.environ["GOOGLE_API_KEY"] = st.secrets["GEMINI_API_KEY"]
if "GOOGLE_API_KEY" in st.secrets:
    os.environ["GOOGLE_API_KEY"] = st.secrets["GOOGLE_API_KEY"]

# load_all_caches function # Moved inside main()
# find_in_cache function # Moved inside main()

def main():
    st.title("AI阪口源太")
    st.markdown("---")
    
    # セッション状態の初期化
    if "messages" not in st.session_state:
        st.session_state.messages = []
        
    if "current_video" not in st.session_state:
        # 初期状態は待機動画
        st.session_state.current_video = "idle_blink.webm"

    # from core_paths import LOCAL_STATIC_DIR # Already imported at top, but keeping for context of the instruction
    init_video_path = str(LOCAL_STATIC_DIR / st.session_state.current_video)
    
    # --- アバターの初期描画 (重い処理の前に即時描画) ---
    avatar_container = st.empty()
    with avatar_container:
        if os.path.exists(init_video_path):
            st.video(init_video_path, autoplay=True, loop=True)
        else:
            # 動画がない場合のフォールバック画像
            poster_path = str(LOCAL_STATIC_DIR / "poster_idle.jpg")
            if os.path.exists(poster_path):
                st.image(poster_path, use_container_width=True)
            else:
                st.info("アバター読み込み中...")

    # 履歴の表示
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])
            if msg.get("audio_bytes"):
                st.audio(msg["audio_bytes"], format="audio/mp3")

    user_input = st.chat_input("💬 質問を入力してください (例: 与那国島の未来について)")

    if user_input:
        # ユーザー入力を履歴に追加して表示
        st.session_state.messages.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.write(user_input)
            
        with st.chat_message("assistant"):
            with st.spinner("考え中..."):
                # ここで初めて重いモジュールをロード＆処理
                import json
                import logging
                import base64
                from core_ai_worker import normalize_text, generate_response
                from tts import synthesize_speech
                
                logging.basicConfig(level=logging.INFO)
                logger = logging.getLogger(__name__)
                
                def load_all_caches():
                    cache_combined = []
                    master_file = LOCAL_STATIC_DIR / "faq_cache.json"
                    if master_file.exists():
                        try:
                            with open(master_file, "r", encoding="utf-8") as f:
                                data = json.load(f)
                                if isinstance(data, list):
                                    for item in data:
                                        if isinstance(item, dict):
                                            cache_combined.append(item)
                        except Exception as e:
                            logger.error(f"Failed to load master cache: {e}")
                
                    extra_file = LOCAL_STATIC_DIR / "extra_cache.json"
                    if extra_file.exists():
                        try:
                            with open(extra_file, "r", encoding="utf-8") as f:
                                data = json.load(f)
                                if isinstance(data, list):
                                    for item in data:
                                        if isinstance(item, dict):
                                            cache_combined.append(item)
                        except Exception as e:
                            logger.error(f"Failed to load extra cache: {e}")
                    return cache_combined

                def find_in_cache(question: str, caches: list):
                    norm_q = normalize_text(question)
                    if not norm_q: return None
                    for item in caches:
                        try:
                            if "question" in item and "response_text" in item:
                                if normalize_text(str(item["question"])) == norm_q:
                                    return item
                        except:
                            pass
                    return None

                try:
                    caches = load_all_caches()
                    match = find_in_cache(user_input, caches)
                    
                    audio_bytes = None
                    if match:
                        response_text = str(match["response_text"])
                        emotion = str(match.get("emotion", "normal")).lower()
                        audio_b64 = match.get("audio_b64", "")
                    else:
                        api_key = st.secrets.get("FINAL_MASTER_KEY") or st.secrets.get("GOOGLE_API_KEY") or ""
                        creds_json = st.secrets.get("GOOGLE_APPLICATION_CREDENTIALS_JSON") or ""
                        p_key = st.secrets.get("GCP_PRIVATE_KEY") or ""
                        c_email = st.secrets.get("GCP_CLIENT_EMAIL") or ""
                        
                        response_text, emotion = generate_response(user_input, api_key=api_key, use_cache=False)
                        emotion = emotion.lower()
                        audio_b64 = synthesize_speech(response_text, creds_json=creds_json, private_key=p_key, client_email=c_email, use_cache=False)
                    
                    # 動画表示要素を決定し、セッションに保存してアバター枠を更新
                    video_filename = "talking_normal.webm"
                    if "idle" in emotion: video_filename = "idle_blink.webm"
                    elif "strong" in emotion: video_filename = "talking_strong.webm"
                    elif "wait" in emotion: video_filename = "talking_wait.webm"
                    
                    st.session_state.current_video = video_filename
                    video_path = str(LOCAL_STATIC_DIR / video_filename)
                    
                    with avatar_container:
                        if os.path.exists(video_path):
                            st.video(video_path, autoplay=True, loop=True)
                        else:
                            poster_path = str(LOCAL_STATIC_DIR / "poster_idle.jpg")
                            if os.path.exists(poster_path):
                                st.image(poster_path, use_container_width=True)
                            else:
                                st.error(f"動画ファイルが見つかりません: {video_path}")
                    
                    # 音声デコード
                    if audio_b64:
                        try:
                            audio_bytes = base64.b64decode(audio_b64)
                        except:
                            pass
                            
                    st.write(response_text)
                    if audio_bytes:
                        st.audio(audio_bytes, format="audio/mp3", autoplay=True)
                        
                    st.session_state.messages.append({
                        "role": "assistant", 
                        "content": response_text,
                        "audio_bytes": audio_bytes
                    })

                except Exception as e:
                    st.error(f"エラーが発生しました: {e}")

if __name__ == "__main__":
    main()