import logging
import os
import time
import threading
from queue import Queue, Empty

import streamlit as st
from brain import generate_response
from tts import synthesize_speech

# ============================================================
# Configuration & Worker
# ============================================================
logger = logging.getLogger(__name__)

# --- Cloud Concurrency Limits ---
IS_CLOUD = os.getenv("STREAMLIT_SERVER_BASE_URL", "") != ""
MAX_CONCURRENCY = 10 if IS_CLOUD else 3
SEMAPHORE = threading.Semaphore(MAX_CONCURRENCY)

def _worker_loop(input_queue: Queue, output_queue: Queue, stop_event: threading.Event, 
                 google_api_key: str, creds_json: str, private_key: str, client_email: str):
    """Background thread: Process Gemini and TTS with explicitly injected secrets."""
    logger.info("[Worker] Thread started with injected secrets.")
    while not stop_event.is_set():
        try:
            item = input_queue.get(timeout=1)
        except Empty:
            continue

        # Use Semaphore to limit simultaneous AI/TTS generation
        with SEMAPHORE:
            try:
                # 2. AI Response
                output_queue.put({"type": "progress", "msg": "Thinking..."})
                reply_text, emotion = generate_response(item.message_text, api_key=google_api_key, use_cache=False)
                
                # 2. TTS
                output_queue.put({"type": "progress", "msg": "Synthesizing voice..."})
                audio_b64 = synthesize_speech(reply_text, creds_json=creds_json, 
                                            private_key=private_key, client_email=client_email, 
                                            use_cache=False)
                
                # 3. Final Result
                result = {
                    "type": "result",
                    "audio_b64": audio_b64,
                    "emotion": emotion,
                    "response_text": reply_text,
                    "question": item.message_text if item.source != "system" else "(起動挨拶)",
                    "author": item.author_name,
                    "is_initial_greeting": item.is_initial_greeting
                }
                output_queue.put(result)
                logger.info(f"[Worker] Task complete: {reply_text[:20]}...")

            except Exception as e:
                logger.error(f"[Worker] Task failed: {e}")
                output_queue.put({"type": "error", "msg": f"AI/TTS Error: {str(e)}"})
                time.sleep(2)

    logger.info("[Worker] Thread stopping.")

def init_worker():
    """Starts the background worker thread if not already running."""
    if st.session_state.worker_thread is None:
        # Get secrets once in the main thread
        # 🚀 Secrets をメインスレッドで取得し、Workerへ明示的に渡す
        api_key = st.secrets.get("FINAL_MASTER_KEY") or st.secrets.get("GOOGLE_API_KEY") or ""
        creds_json = st.secrets.get("GOOGLE_APPLICATION_CREDENTIALS_JSON") or ""
        # Individual keys
        p_key = st.secrets.get("GCP_PRIVATE_KEY") or ""
        c_email = st.secrets.get("GCP_CLIENT_EMAIL") or ""

        stop_event = threading.Event()
        thread = threading.Thread(
            target=_worker_loop,
            args=(st.session_state.queue, st.session_state.output_queue, stop_event, 
                  api_key, creds_json, p_key, c_email),
            daemon=True,
            name="avatar-worker"
        )
        thread.start()
        st.session_state.worker_thread = thread
        st.session_state.worker_stop = stop_event
        logger.info("[App] Background worker started.")
