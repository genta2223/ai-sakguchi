import logging
import os
import time
import threading
import json
import numpy as np
from queue import Queue, Empty

import re
import streamlit as st
from brain import generate_response
from tts import synthesize_speech
from core_paths import LOCAL_STATIC_DIR
from langchain_google_genai import GoogleGenerativeAIEmbeddings

def normalize_text(text: str) -> str:
    """文字列の正規化：不要な記号や空白を削除（キャッシュの柔軟な照合用）"""
    if not text: return ""
    # 全角半角空白、改行、感嘆符などを全て除去
    return re.sub(r'[…\.\?\!。？！\s\n\r　]+', '', text).strip()

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
            
        # 照合用キーを事前に準備
        for c_item in FAQ_CACHE:
            if "question" in c_item:
                c_item["norm_key"] = normalize_text(c_item["question"])
                
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
                
                cache_to_repair = None
                
                if FAQ_CACHE and FAQ_EMBEDDINGS is not None and EMBEDDER and not is_system and not is_greeting:
                    try:
                        output_queue.put({"type": "debug", "msg": "🔍 思考プロセス: キャッシュを検索中..."})
                        norm_query = normalize_text(item.message_text)
                        best_idx = -1
                        max_sim = 0.0
                        
                        # 1. まずは正規化文字列で完全一致チェック
                        for i, cache_item in enumerate(FAQ_CACHE):
                            if cache_item.get("norm_key") == norm_query:
                                logger.info(f"[Cache Debug] ⚡ EXACT MATCH HIT! (正規化キー完全一致)")
                                output_queue.put({"type": "debug", "msg": f"✅ 思考プロセス: 正規化キー完全一致! (質問: {cache_item['question'][:15]}...)"})
                                best_idx = i
                                max_sim = 1.0
                                break
                        
                        # 2. 完全一致しなかった場合はベクトル検索
                        if best_idx == -1:
                            query_embed = EMBEDDER.embed_query(item.message_text)
                            query_vector = np.array(query_embed)
                            
                            norms = np.linalg.norm(FAQ_EMBEDDINGS, axis=1) * np.linalg.norm(query_vector)
                            similarities = np.dot(FAQ_EMBEDDINGS, query_vector) / norms
                            
                            best_idx = int(np.argmax(similarities))
                            max_sim = float(similarities[best_idx])
                            logger.info(f'[Cache Debug] 入力: "{item.message_text}" | 最も似ているFAQ: "{FAQ_CACHE[best_idx]["question"]}" | 類似度スコア: {max_sim:.4f}')
                            output_queue.put({"type": "debug", "msg": f"🧠 思考プロセス: 類似度スコア {max_sim:.4f} (候補: {FAQ_CACHE[best_idx]['question'][:15]}...)"})
                        
                        if max_sim >= 0.75:
                            cached_ans = FAQ_CACHE[best_idx].get("response_text", "")
                            rejection_phrases = ["答えられません", "学習中", "エラー", "申し訳ありません"]
                            is_rejected = any(rp in cached_ans for rp in rejection_phrases)
                            
                            if is_rejected:
                                logger.info(f"[Worker] ⚠️ Cache contains rejection phrase. Invalidating and flagging for auto-repair. (Idx: {best_idx})")
                                cache_to_repair = best_idx
                            else:
                                logger.info(f"[Worker] FAQ Cache HIT! Similarity: {max_sim:.2f} (Matched: {FAQ_CACHE[best_idx]['question']})")
                                logger.info("[Cache Debug] ⚡ CACHE HIT! (生成をスキップします)")
                                output_queue.put({"type": "debug", "msg": "⚡ 思考プロセス: 十分な一致。生成をスキップしキャッシュを返します。"})
                                best_match_item = FAQ_CACHE[best_idx]
                        else:
                            logger.info("[Cache Debug] 🧠 CACHE MISS. (LLM生成に進みます)")
                            output_queue.put({"type": "debug", "msg": "📝 思考プロセス: キャッシュミス。LLMによる新規生成を構成中..."})
                    except Exception as e:
                        logger.warning(f"[Worker] Embedding check failed: {e}")
                        output_queue.put({"type": "debug", "msg": f"⚠️ 思考プロセス: キャッシュ確認エラー ({e})。LLM生成に切り替え。"})

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
                output_queue.put({"type": "debug", "msg": f"🤖 思考プロセス: LLM回答生成完了 ({len(reply_text)}文字, 感情:{emotion})"})
                
                # 2. TTS
                output_queue.put({"type": "progress", "msg": "Synthesizing voice..."})
                output_queue.put({"type": "debug", "msg": "🎤 思考プロセス: 音声合成をリクエスト中..."})
                audio_b64 = synthesize_speech(reply_text, creds_json=creds_json, 
                                            private_key=private_key, client_email=client_email, 
                                            use_cache=False)
                
                # 3. Auto-Repair Cache if needed
                if cache_to_repair is not None:
                    # Verify new response is good
                    rejection_phrases = ["答えられません", "学習中", "エラー", "申し訳ありません"]
                    if not any(rp in reply_text for rp in rejection_phrases):
                        logger.info(f"🔧 [Worker] Auto-repairing cache index {cache_to_repair} with new valid answer.")
                        FAQ_CACHE[cache_to_repair]["response_text"] = reply_text
                        FAQ_CACHE[cache_to_repair]["emotion"] = emotion
                        FAQ_CACHE[cache_to_repair]["audio_b64"] = audio_b64
                        try:
                            with open(LOCAL_STATIC_DIR / "faq_cache.json", "w", encoding="utf-8") as f:
                                json.dump(FAQ_CACHE, f, ensure_ascii=False, indent=2)
                        except Exception as e:
                            logger.error(f"Failed to write repaired cache back to disk: {e}")

                # 4. Final Result
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
