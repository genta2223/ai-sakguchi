"""
tts.py — Google Cloud Text-to-Speech for Streamlit Cloud
Generates MP3 audio from text, returns base64-encoded string for browser playback.
"""
import base64
import json
import logging

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


@st.cache_resource
def _get_tts_client():
    """Create and cache Google Cloud TTS client using st.secrets."""
    creds_json = st.secrets.get("GOOGLE_APPLICATION_CREDENTIALS_JSON", "")
    if creds_json:
        info = json.loads(creds_json)
        credentials = service_account.Credentials.from_service_account_info(info)
        client = texttospeech.TextToSpeechClient(credentials=credentials)
    else:
        # Fall back to default credentials (e.g., local dev with GOOGLE_APPLICATION_CREDENTIALS env var)
        client = texttospeech.TextToSpeechClient()
    return client


def synthesize_speech(text: str) -> str:
    """
    Generate speech from text using Google Cloud TTS.

    Args:
        text: Japanese text to synthesize.

    Returns:
        Base64-encoded MP3 audio string (ready for HTML audio src).
    """
    # Apply name readings
    for kanji, reading in NAME_READINGS.items():
        text = text.replace(kanji, reading)

    client = _get_tts_client()

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
