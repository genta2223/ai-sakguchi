"""
tts.py — Google Cloud Text-to-Speech for Streamlit Cloud
Generates MP3 audio from text, returns base64-encoded string for browser playback.
"""
import base64
import json
import logging
import threading
import textwrap

import streamlit as st
from google.cloud import texttospeech
from google.oauth2 import service_account

import jaconv
from janome.tokenizer import Tokenizer

logger = logging.getLogger(__name__)

# 固有名詞の読み辞書
NAME_READINGS = {
    "阪口源太": "さかぐちげんた",
    "坂口源太": "さかぐちげんた",
    "阪口": "さかぐち",
    "坂口": "さかぐち",
    "源太": "げんた",
    "安野": "あんの",
    "AI町政報告会": "AIちょうせいほうこくかい",
    "町政報告会": "ちょうせいほうこくかい",
}


from pathlib import Path

def _create_client(creds_json=None, private_key=None, client_email=None):
    """
    Creates Google Cloud TTS client prioritizing Streamlit Cloud Secrets (flat keys), 
    then falling back to a physical JSON file for local development.
    """
    try:
        # 1. PRIMARY: Streamlit Cloud Secrets (Individual flat keys)
        if "GCP_PRIVATE_KEY" in st.secrets and "GCP_CLIENT_EMAIL" in st.secrets:
            import re
            raw_key = st.secrets.get("GCP_PRIVATE_KEY", "")
            
            # --- Binary-Clean Surgery ---
            # 1. 前後の空白、改行、および引用符 (", ') を徹底的に削除
            clean_key = raw_key.strip().strip('"').strip("'")
            
            # 2. クラウド特有のエスケープ文字 (\\n) を実際の改行へ（もしあれば）
            if "\\n" in clean_key and "\n" not in clean_key:
                clean_key = clean_key.replace("\\n", "\n")
            
            # 3. Base64データ部分のみを抽出 (ヘッダー/フッターを除去して純粋な本体へ)
            body = clean_key.replace("-----BEGIN PRIVATE KEY-----", "")
            body = body.replace("-----END PRIVATE KEY-----", "")
            # Base64として有効な文字 (A-Z, a-z, 0-9, +, /, =) 以外をすべて排除
            body_pure = re.sub(r'[^A-Za-z0-9+/=]', '', body)
            
            # 4. 64文字ごとに改行を入れる厳密なPEMフォーマットへ再構築
            lines = [body_pure[i:i+64] for i in range(0, len(body_pure), 64)]
            final_pem = "-----BEGIN PRIVATE KEY-----\n" + "\n".join(lines) + "\n-----END PRIVATE KEY-----\n"
            
            info = {
                "type": "service_account",
                "private_key": final_pem,
                "client_email": st.secrets["GCP_CLIENT_EMAIL"],
                "token_uri": "https://oauth2.googleapis.com/token",
                "project_id": st.secrets["GCP_CLIENT_EMAIL"].split("@")[1].split(".")[0]
            }
            credentials = service_account.Credentials.from_service_account_info(info)
            logger.info("[TTS] Loaded credentials using Binary-Clean PEM Rebuilder.")
            return texttospeech.TextToSpeechClient(credentials=credentials)

        # 2. SECONDARY: Direct JSON file (Local development)
        credential_path = "C:/Users/genta/anno-ai-avatar-main/streamlit_app/.streamlit/gen-lang-client-0030599774-93fd0a8a3cb3.json"
        json_path = Path(credential_path)
        # Fallback for relative context
        alt_path = Path("streamlit_app/.streamlit/gen-lang-client-0030599774-93fd0a8a3cb3.json")
        
        target_path = None
        if json_path.exists():
            target_path = str(json_path)
        elif alt_path.exists():
            target_path = str(alt_path)

        if target_path:
            logger.info(f"[TTS] Loaded credentials from file: {target_path}")
            return texttospeech.TextToSpeechClient.from_service_account_file(target_path)

        # 3. FALLBACK: Manual arguments (passed from worker)
        if private_key and client_email:
            info = {
                "type": "service_account",
                "project_id": client_email.split("@")[1].split(".")[0],
                "private_key": private_key.replace("\\n", "\n").strip(),
                "client_email": client_email,
                "token_uri": "https://oauth2.googleapis.com/token",
            }
            credentials = service_account.Credentials.from_service_account_info(info)
            return texttospeech.TextToSpeechClient(credentials=credentials)

        # Final Fallback: Attempt default discovery
        logger.warning("[TTS] No specific credentials found, falling back to default discovery.")
        return texttospeech.TextToSpeechClient()

    except Exception as e:
        logger.error(f"[TTS] Initialization failed: {e}")
        if threading.current_thread() is threading.main_thread():
             logger.warning("[TTS] Falling back to default client in main thread.")
             return texttospeech.TextToSpeechClient()
        raise e

@st.cache_resource
def _get_tts_client_cached():
    """Cached wrapper for UI thread."""
    return _create_client()


def synthesize_speech(text: str, creds_json: str = None, private_key: str = None, client_email: str = None, use_cache: bool = True) -> str:
    """
    Generate speech from text using Google Cloud TTS.
    """
    # Apply name readings
    for kanji, reading in NAME_READINGS.items():
        text = text.replace(kanji, reading)

    if use_cache:
        client = _get_tts_client_cached()
    else:
        client = _create_client(creds_json, private_key, client_email)

    synthesis_input = texttospeech.SynthesisInput(text=text)
    voice = texttospeech.VoiceSelectionParams(
        language_code="ja-JP",
        name="ja-JP-Neural2-C",  # Male, Neural2
    )
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
        speaking_rate=1.0,
        pitch=0.0,
    )

    logger.info(f"[TTS] Synthesizing: '{text[:40]}...'")
    response = client.synthesize_speech(
        input=synthesis_input, voice=voice, audio_config=audio_config
    )

    audio_bytes = response.audio_content
    if len(audio_bytes) < 100:
        raise RuntimeError(f"TTS returned too-small audio ({len(audio_bytes)} bytes)")

    logger.info(f"[TTS] OK: {len(audio_bytes)} bytes")
    audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
    return audio_b64
