import json
import logging
import sys
from pathlib import Path
from tqdm import tqdm

from core_paths import APP_DIR, LOCAL_STATIC_DIR
from tts import synthesize_speech

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_secrets():
    try:
        if sys.version_info >= (3, 11):
            import tomllib as toml
        else:
            import toml
        with open(r"c:\Users\genta\anno-ai-avatar-main\streamlit_app\.streamlit\secrets.toml", "rb") as f:
            secret_data = toml.load(f)
            return secret_data
    except Exception as e:
        logger.warning(f"Could not load secrets.toml: {e}")
        return {}

def build_faq_audio():
    cache_file = LOCAL_STATIC_DIR / "faq_cache.json"
    if not cache_file.exists():
        logger.error(f"Cannot find {cache_file}")
        return

    with open(cache_file, "rb") as f:
        raw_data = f.read()

    # Check for BOM contamination
    has_bom_utf8 = raw_data.startswith(b'\xef\xbb\xbf')
    has_bom_utf16le = raw_data.startswith(b'\xff\xfe')
    has_bom_utf16be = raw_data.startswith(b'\xfe\xff')
    
    if has_bom_utf8 or has_bom_utf16le or has_bom_utf16be:
        logger.error(f"⚠️ 外部からの汚染 (BOM混入) を検出しました: {cache_file.name}。BOMを除去して救出します。")
        try:
            text_data = raw_data.decode("utf-8-sig")
        except UnicodeDecodeError:
            try:
                text_data = raw_data.decode("utf-16")
            except UnicodeDecodeError:
                text_data = raw_data.decode("utf-8", errors="ignore")
        
        faq_cache = json.loads(text_data)
        
        # Re-save immediately as pure UTF-8 only if not empty
        if faq_cache:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(faq_cache, f, ensure_ascii=False, indent=2)
            logger.info(f"🔧 キャッシュファイルからBOMを除去し、中身を維持したまま純粋なUTF-8で上書き保存(救出)しました。")
        else:
            logger.error(f"⚠️ 救出したデータが空のため、破壊防止としてファイル上書きをスキップしました。")
    else:
        text_data = raw_data.decode("utf-8")
        faq_cache = json.loads(text_data)

    logger.info(f"Loaded {len(faq_cache)} items from faq_cache.json.")

    secrets = get_secrets()
    private_key = secrets.get("GCP_PRIVATE_KEY", "")
    client_email = secrets.get("GCP_CLIENT_EMAIL", "")

    updates_made = 0
    for item in tqdm(faq_cache, desc="Generating Audio"):
        if item.get("audio_b64") is None:
            try:
                audio_b64 = synthesize_speech(
                    text=item["response_text"],
                    private_key=private_key,
                    client_email=client_email,
                    use_cache=False
                )
                item["audio_b64"] = audio_b64
                updates_made += 1
            except Exception as e:
                logger.error(f"Failed to generate audio for question '{item.get('question')}': {e}")
    
    if updates_made > 0:
        if faq_cache:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(faq_cache, f, ensure_ascii=False, indent=2)
            logger.info(f"Updated {updates_made} items with audio and saved to {cache_file.name}")
        else:
            logger.error(f"⚠️ 更新データが空のため、破壊防止としてファイル上書きをスキップしました。")
    else:
        logger.info("No missing audio found, zero updates made.")

if __name__ == "__main__":
    build_faq_audio()
