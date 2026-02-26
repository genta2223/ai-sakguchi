import logging
import os
import time
import threading
import json
import numpy as np
from queue import Queue, Empty

import streamlit as st
from brain import generate_response
from tts import synthesize_speech
from core_paths import LOCAL_STATIC_DIR
from langchain_google_genai import GoogleGenerativeAIEmbeddings

# ============================================================
# Configuration & Worker
# ============================================================
logger = logging.getLogger(__name__)

# --- Cloud Concurrency Limits ---
IS_CLOUD = os.getenv("STREAMLIT_SERVER_BASE_URL", "") != ""
MAX_CONCURRENCY = 10 if IS_CLOUD else 3
SEMAPHORE = threading.Semaphore(MAX_CONCURRENCY)

FAQ_CACHE = []
FAQ_EMBEDDINGS = None
EMBEDDER = None

def init_faq_cache(api_key: str):
    global FAQ_CACHE, FAQ_EMBEDDINGS, EMBEDDER
    if FAQ_CACHE: return
    
    cache_file = LOCAL_STATIC_DIR / "faq_cache.json"
    if not cache_file.exists():
        return
        
    try:
        with open(cache_file, "r", encoding="utf-8") as f:
            FAQ_CACHE = json.load(f)
            
        EMBEDDER = GoogleGenerativeAIEmbeddings(
            model="models/gemini-embedding-001",
            google_api_key=api_key
        )
        questions = [item["question"] for item in FAQ_CACHE]
        if questions:
            embeddings = EMBEDDER.embed_documents(questions)
            FAQ_EMBEDDINGS = np.array(embeddings)
            logger.info(f"[Worker] Loaded {len(FAQ_CACHE)} FAQs and pre-calculated embeddings.")
            logger.info(f"[Cache Debug] FAQキャッシュを{len(FAQ_CACHE)}件ロードし、ベクトル化を完了しました。")
    except Exception as e:
        logger.error(f"[Worker] Failed to init FAQ cache: {e}")

def _worker_loop(input_queue: Queue, output_queue: Queue, stop_event: threading.Event, 
                 google_api_key: str, creds_json: str, private_key: str, client_email: str):
    """Background thread: Process Gemini and TTS with explicitly injected secrets."""
    logger.info("[Worker] Thread started with injected secrets (Bucket Relay).")
    init_faq_cache(google_api_key)
    while not stop_event.is_set():
        try:
            item = input_queue.get(timeout=1)
        except Empty:
            continue

        # Use Semaphore to limit simultaneous AI/TTS generation
        with SEMAPHORE:
            try:
                best_match_item = None
                is_system = getattr(item, "source", None) == "system"
                is_greeting = getattr(item, "is_initial_greeting", False)
                
                if FAQ_CACHE and FAQ_EMBEDDINGS is not None and EMBEDDER and not is_system and not is_greeting:
                    try:
                        query_embed = EMBEDDER.embed_query(item.message_text)
                        query_vector = np.array(query_embed)
                        
                        # Cosine similarity
                        norms = np.linalg.norm(FAQ_EMBEDDINGS, axis=1) * np.linalg.norm(query_vector)
                        similarities = np.dot(FAQ_EMBEDDINGS, query_vector) / norms
                        
                        best_idx = np.argmax(similarities)
                        max_sim = similarities[best_idx]
                        
                        logger.info(f'[Cache Debug] 入力: "{item.message_text}" | 最も似ているFAQ: "{FAQ_CACHE[best_idx]["question"]}" | 類似度スコア: {max_sim:.4f}')
                        
                        if max_sim >= 0.75:
                            logger.info(f"[Worker] FAQ Cache HIT! Similarity: {max_sim:.2f} (Matched: {FAQ_CACHE[best_idx]['question']})")
                            logger.info("[Cache Debug] ⚡ CACHE HIT! (生成をスキップします)")
                            best_match_item = FAQ_CACHE[best_idx]
                        else:
                            logger.info("[Cache Debug] 🧠 CACHE MISS. (LLM生成に進みます)")
                    except Exception as e:
                        logger.warning(f"[Worker] Embedding check failed: {e}")

                if best_match_item:
                    reply_text = best_match_item["response_text"]
                    emotion = best_match_item.get("emotion", "Neutral")
                    audio_b64 = best_match_item.get("audio_b64")
                    
                    if not audio_b64:
                        logger.warning("[Worker] FAQ Cache has no audio. Generating...")
                        audio_b64 = synthesize_speech(reply_text, creds_json=creds_json, 
                                                    private_key=private_key, client_email=client_email, 
                                                    use_cache=False)
                    
                    result = {
                        "type": "result",
                        "audio_b64": audio_b64,
                        "emotion": emotion,
                        "response_text": reply_text,
                        "question": item.message_text if not is_system else "(起動挨拶)",
                        "author": getattr(item, "author_name", ""),
                        "is_initial_greeting": getattr(item, "is_initial_greeting", False)
                    }
                    output_queue.put(result)
                    logger.info(f"[Worker] Task complete (FAQ Cache): {reply_text[:20]}...")
                    continue
                
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
                    "question": item.message_text if not is_system else "(起動挨拶)",
                    "author": getattr(item, "author_name", ""),
                    "is_initial_greeting": getattr(item, "is_initial_greeting", False)
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
        # 🚀 Secrets をメインスレッドで取得し、Workerへ明示的に渡す (バケツリレー)
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
