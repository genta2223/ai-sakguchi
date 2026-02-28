import time
import sys
import os

from core_ai_worker import normalize_text
import json

def test_legacy():
    start = time.time()
    with open('static/faq_cache.json', 'r', encoding='utf-8') as f:
        cache = json.load(f)
    
    query = "与那国馬活用プロジェクトの具体的な進捗状況はどうなっていますか？"
    norm_query = normalize_text(query)
    
    for c in cache:
        if "question" in c:
            c["norm_key"] = normalize_text(c["question"])
            
    hit = None
    for c in cache:
        if c.get("norm_key") == norm_query:
            hit = c
            break
            
    elapsed = time.time() - start
    if hit:
        print(f"PASS: Instant hit without external API in {elapsed*1000:.2f}ms.\nHit Response: {hit['response_text'][:30]}...")
    else:
        print("FAIL: Cache miss.")

if __name__ == "__main__":
    test_legacy()
