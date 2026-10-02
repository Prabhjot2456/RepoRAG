"""
Embedding abstraction.
Uses Google Gemini API for embeddings instead of local models to save RAM.
"""

from __future__ import annotations

import httpx
import time
from typing import List

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


def embed_texts(texts: List[str], batch_size: int = 64) -> List[List[float]]:
    """
    Embed a list of texts using Gemini API.
    Returns a list of embedding vectors.
    """
    if not texts:
        return []

    if not settings.gemini_api_key:
        raise ValueError("GEMINI_API_KEY is missing. Cannot generate embeddings.")

    all_embeddings = []
    
    # Process in batches
    for i in range(0, len(texts), batch_size):
        batch_texts = texts[i : i + batch_size]
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:batchEmbedContents?key={settings.gemini_api_key}"
        
        requests = []
        for text in batch_texts:
            # Handle empty texts by providing a space, Gemini API fails on empty strings
            safe_text = text if text.strip() else " "
            requests.append({
                "model": "models/gemini-embedding-001",
                "content": {"parts": [{"text": safe_text}]}
            })
            
        retry_count = 0
        while retry_count < 5:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(url, json={"requests": requests})
                
                if response.status_code == 429:
                    try:
                        error_data = response.json()
                        error_msg = error_data.get("error", {}).get("message", "")
                        if "exceeded your current quota" in error_msg.lower():
                            logger.error("gemini_quota_exceeded", text=response.text)
                            raise Exception("Google Gemini API Quota Exceeded! You have hit your daily limit or billing limit. Please check your Google AI Studio dashboard.")
                    except Exception as e:
                        if "Google Gemini API Quota Exceeded" in str(e):
                            raise e

                    # Rate limit hit, wait and retry
                    wait_time = 4 * (2 ** retry_count)  # 4s, 8s, 16s...
                    logger.warning("gemini_rate_limit_hit", waiting=wait_time, retry=retry_count)
                    time.sleep(wait_time)
                    retry_count += 1
                    continue
                    
                if response.status_code != 200:
                    logger.error("gemini_embedding_failed", status=response.status_code, text=response.text)
                    raise Exception(f"Gemini API returned {response.status_code}: {response.text}")
                    
                data = response.json()
                if "embeddings" not in data:
                    raise Exception(f"Unexpected Gemini response format: {data}")
                    
                batch_embeddings = [e["values"] for e in data["embeddings"]]
                all_embeddings.extend(batch_embeddings)
                break
                
        if retry_count == 5:
            raise Exception("Gemini API rate limit exceeded. Tried 5 times and failed.")
            
        # Add a small delay between batches to respect the 15 requests/minute free tier limit
        time.sleep(2)

            
    return all_embeddings


def embed_query(query: str) -> List[float]:
    """Embed a single query string."""
    return embed_texts([query])[0]

