import os
import sys
from pathlib import Path

# 🚀 Streamlitがstaticフォルダを正しく認識するためのハック
sys.path.append(str(Path(__file__).parent))

import streamlit as st
import json
import logging
import base64

from core_paths import LOCAL_STATIC_DIR, PathManager
from core_ai_worker import normalize_text, generate_response
from tts import synthesize_speech

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

def load_all_caches():
    """安全にキャッシュを読み込む (厳格な型チェックとtry-exceptガードレール)"""
    cache_combined = []
    
    # 1. Master Cache
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

    # 2. Extra Cache
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
    """キャッシュから質問を完全一致(正規化後)で探す (型チェックガード済み)"""
    norm_q = normalize_text(question)
    if not norm_q:
        return None
        
    for item in caches:
        try:
            # 必須フィールドの存在と型をチェック
            if "question" in item and "response_text" in item:
                q_text = str(item["question"])
                if normalize_text(q_text) == norm_q:
                    return item
        except Exception as e:
            logger.warning(f"Cache parse error: {e}")
    return None

def main():
    st.title("AI阪口源太")
    st.markdown("---")

    # キャッシュを読み込む
    caches = load_all_caches()
    
    # セッション状態の初期化
    if "messages" not in st.session_state:
        st.session_state.messages = []

    # 履歴の表示
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])
            if msg.get("video_path") and os.path.exists(msg["video_path"]):
                st.video(msg["video_path"], autoplay=False, loop=False)

    user_input = st.chat_input("💬 質問を入力してください")

    if user_input:
        # ユーザー入力を履歴に追加して表示
        st.session_state.messages.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.write(user_input)
            
        with st.chat_message("assistant"):
            with st.spinner("考え中..."):
                try:
                    # 1. 厳格なキャッシュ検索（同期）
                    match = find_in_cache(user_input, caches)
                    
                    if match:
                        response_text = str(match["response_text"])
                        emotion = str(match.get("emotion", "normal")).lower()
                        audio_b64 = match.get("audio_b64", "")
                        logger.info("CACHE HIT!")
                    else:
                        logger.info("CACHE MISS! Synchronous Gemini generation falls back.")
                        api_key = st.secrets.get("FINAL_MASTER_KEY") or st.secrets.get("GOOGLE_API_KEY") or ""
                        creds_json = st.secrets.get("GOOGLE_APPLICATION_CREDENTIALS_JSON") or ""
                        p_key = st.secrets.get("GCP_PRIVATE_KEY") or ""
                        c_email = st.secrets.get("GCP_CLIENT_EMAIL") or ""
                        
                        response_text, emotion = generate_response(user_input, api_key=api_key, use_cache=False)
                        emotion = emotion.lower()
                        audio_b64 = synthesize_speech(response_text, creds_json=creds_json, private_key=p_key, client_email=c_email, use_cache=False)
                    
                    # 2. テキスト表示
                    st.write(response_text)
                    
                    # 3. 動画表示要素を決定
                    video_filename = "talking_normal.webm"
                    if "idle" in emotion: video_filename = "idle_blink.webm"
                    elif "strong" in emotion: video_filename = "talking_strong.webm"
                    elif "wait" in emotion: video_filename = "talking_wait.webm"
                    
                    video_path = str(LOCAL_STATIC_DIR / video_filename)
                    if os.path.exists(video_path):
                        st.video(video_path, autoplay=True, loop=True)
                    else:
                        st.error(f"動画ファイルが見つかりません: {video_path}")
                        
                    # 4. 音声表示
                    if audio_b64:
                        try:
                            audio_bytes = base64.b64decode(audio_b64)
                            st.audio(audio_bytes, format="audio/mp3", autoplay=True)
                        except Exception as decode_e:
                            logger.error(f"Failed to decode audio base64: {decode_e}")
                            
                    # アシスタントメッセージを履歴に保存 (動画パスも保存して再描画時に静的に出せるようにする)
                    st.session_state.messages.append({
                        "role": "assistant", 
                        "content": response_text,
                        "video_path": video_path if os.path.exists(video_path) else None,
                        # 音声は自動再生されるとうるさいので履歴には表示しないか、autoplayをオフにできるが、シンプルにするため履歴からは動画のみ表示
                    })
                        
                except Exception as e:
                    logger.error(f"Error processing question: {e}", exc_info=True)
                    st.error(f"エラーが発生しました: {e}")

if __name__ == "__main__":
    main()