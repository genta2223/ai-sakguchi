import time
import os
import json
from queue import Queue
import threading
from core_ai_worker import normalize_text, _worker_loop, init_faq_cache

class DummyItem:
    def __init__(self, text, author="test"):
        self.message_text = text
        self.author_name = author
        self.source = "direct"

def test_miss():
    init_faq_cache(os.getenv("GOOGLE_API_KEY", "dummy"))
    
    in_q = Queue()
    out_q = Queue()
    stop = threading.Event()
    
    in_q.put(DummyItem("これは新しい野良質問ですが大丈夫ですか？"))
    
    # We won't actually run the full AI thread here without keys, but we can verify the file logic.
    # Instead, let's just create a dummy extra_cache to ensure formatting.
    extra_cache_file = 'static/extra_cache.json'
    dummy_data = [{
        "question": "これはテストの野良質問です。",
        "response_text": "野良質問に対する回答です。",
        "emotion": "Neutral",
        "audio_b64": "dummy",
        "source": "extra"
    }]
    with open(extra_cache_file, 'w', encoding='utf-8') as f:
        json.dump(dummy_data, f, ensure_ascii=False, indent=2)

    print("Created mock extra_cache.json")
    
if __name__ == "__main__":
    test_miss()
