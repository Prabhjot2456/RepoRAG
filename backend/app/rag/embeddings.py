"""
Embedding abstraction.
Uses Google Gemini API for embeddings instead of local models to save RAM.
"""

from __future__ import annotations

import httpx
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
            
        with httpx.Client(timeout=30.0) as client:
            response = client.post(url, json={"requests": requests})
            
            if response.status_code != 200:
                logger.error("gemini_embedding_failed", status=response.status_code, text=response.text)
                raise Exception(f"Gemini API returned {response.status_code}: {response.text}")
                
            data = response.json()
            if "embeddings" not in data:
                raise Exception(f"Unexpected Gemini response format: {data}")
                
            batch_embeddings = [e["values"] for e in data["embeddings"]]
            all_embeddings.extend(batch_embeddings)
            
    return all_embeddings


def embed_query(query: str) -> List[float]:
    """Embed a single query string."""
    return embed_texts([query])[0]

