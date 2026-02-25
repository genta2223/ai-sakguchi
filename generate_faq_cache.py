import json
import logging
import os
import streamlit as st
from pathlib import Path
from tqdm import tqdm
import sys

import google.generativeai as genai
from langchain_community.vectorstores import FAISS
from langchain_google_genai import GoogleGenerativeAIEmbeddings

from core_paths import APP_DIR, LOCAL_STATIC_DIR
from brain import check_ng, _build_system_prompt, get_multiple_qa, get_multiple_knowledge

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATA_DIR = APP_DIR / "data"
FAISS_KNOWLEDGE_DB_DIR = DATA_DIR / "faiss_knowledge_db"

def get_api_key():
    try:
        if sys.version_info >= (3, 11):
            import tomllib as toml
        else:
            import toml
        with open(r"c:\Users\genta\anno-ai-avatar-main\streamlit_app\.streamlit\secrets.toml", "rb") as f:
            secret_data = toml.load(f)
            return secret_data.get("FINAL_MASTER_KEY") or secret_data.get("GOOGLE_API_KEY")
    except Exception as e:
        logger.warning(f"Could not load secrets.toml: {e}")
        return os.environ.get("GOOGLE_API_KEY")

def extract_top_30_questions_from_rag():
    api_key = get_api_key()
    
    if not api_key:
        logger.error("No API key found.")
        return []

    # Load FAISS
    embeddings = GoogleGenerativeAIEmbeddings(
        model="models/gemini-embedding-001",
        google_api_key=api_key
    )
    vector = FAISS.load_local(
        str(FAISS_KNOWLEDGE_DB_DIR), embeddings, allow_dangerous_deserialization=True
    )
    
    # Extract all text
    docs = vector.docstore._dict.values()
    all_text = ""
    for doc in docs:
        all_text += doc.page_content + "\n"
        
    logger.info(f"Extracted {len(all_text)} characters from FAISS docstore.")
    
    # Generate Top 30 questions
    prompt = f"""
以下のテキストは与那国町政の議事録データや関連資料（RAG用データ）です。
ここから『町民から最も頻繁に寄せられる、あるいは関心が高い質問』を推測し、上位30件を抽出してください。
出力は質問文のみのリスト（JSONの配列形式）で出力してください。

注意事項:
- 町民の視点に立ったリアルな質問にしてください。
- 阪口源太議員あての質問という想定のトーンにしてください。
- JSON形式の配列（例: ["質問1", "質問2", ...]）のみを出力してください。

データ:
{all_text[:100000]} # Limit to 100k chars for safety if it's too large, but 100k is plenty
"""

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        model_name="gemini-2.0-flash",
        generation_config={"response_mime_type": "application/json"}
    )
    
    response = model.generate_content(prompt)
    try:
        questions = json.loads(response.text)
        return questions
    except json.JSONDecodeError:
        logger.error("Failed to parse JSON response.")
        logger.error(response.text)
        return []

def pre_generate_answers(questions):
    from brain import generate_response
    
    faq_cache = []
    
    api_key = get_api_key()

    for q in tqdm(questions, desc="Generating FAQ Answers"):
        reply_text, emotion = generate_response(q, api_key=api_key, use_cache=False)
        
        # NOTE: If we want to generate TTS audio cache, we can include synthesize_speech here.
        # But for now, we just prepare the text format as requested: "greeting_cache.json と同様の形式"
        # We will save the text and emotion. TTS could be added if needed.
        task_data = {
            "question": q,
            "response_text": reply_text,
            "emotion": emotion,
            "audio_b64": None # audio generation can be skipped for text-only cache or done if specified
        }
        faq_cache.append(task_data)
        
    cache_file = LOCAL_STATIC_DIR / "faq_cache.json"
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(faq_cache, f, ensure_ascii=False, indent=2)
    
    logger.info(f"Saved FAQ cache to {cache_file.name}")

if __name__ == "__main__":
    logger.info("Starting FAQ extraction and answer generation...")
    questions = extract_top_30_questions_from_rag()
    
    if questions:
        logger.info(f"Extracted {len(questions)} questions. Starting answer generation...")
        pre_generate_answers(questions)
    else:
        logger.warning("No questions extracted.")
