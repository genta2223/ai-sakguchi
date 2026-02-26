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

    with open(cache_file, "r", encoding="utf-8") as f:
        faq_cache = json.load(f)

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
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(faq_cache, f, ensure_ascii=False, indent=2)
        logger.info(f"Updated {updates_made} items with audio and saved to {cache_file.name}")
    else:
        logger.info("No missing audio found, zero updates made.")

if __name__ == "__main__":
    build_faq_audio()
