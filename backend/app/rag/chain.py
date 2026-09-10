"""
RAG chain — orchestrates retrieval, context assembly, and LLM call.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional, Tuple

from app.config import settings
from app.llm.provider import get_llm_response
from app.models.schemas import ChatResponse, QueryType, SourceChunk
from app.rag.prompts import OVERVIEW_PROMPT, build_context_string, build_messages
from app.rag.rag_retriever import retrieve_for_query
from app.rag.reranker import rerank
from app.rag.router import classify_query
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _build_sources(
    chunks: List[Dict[str, Any]],
    repo_url: str,
    owner: str,
    repo_name: str,
    default_branch: str,
) -> List[SourceChunk]:
    """Convert retrieved chunks into SourceChunk objects with GitHub URLs."""
    sources = []
    seen = set()

    for chunk in chunks:
        meta = chunk.get("metadata", {})
        file_path = meta.get("file_path", "")
        start_line = meta.get("start_line")
        end_line = meta.get("end_line")

        # Dedup by file_path + start_line
        dedup_key = f"{file_path}:{start_line}"
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        # Build GitHub URL
        github_url = None
        if file_path and owner and repo_name:
            base = f"https://github.com/{owner}/{repo_name}/blob/{default_branch}/{file_path}"
            if start_line and end_line:
                github_url = f"{base}#L{start_line}-L{end_line}"
            elif start_line:
                github_url = f"{base}#L{start_line}"
            else:
                github_url = base

        content = chunk.get("content", "")
        preview = content[:200].strip() if content else None

        sources.append(SourceChunk(
            file_path=file_path,
            start_line=start_line,
            end_line=end_line,
            chunk_type=meta.get("chunk_type"),
            symbol=meta.get("symbol") or None,
            language=meta.get("language") or None,
            content_preview=preview,
            github_url=github_url,
        ))

    return sources[:10]  # Cap at 10 sources


async def run_rag_chain(
    repository_id: str,
    query: str,
    repo_url: str,
    owner: str,
    repo_name: str,
    default_branch: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
    conversation_id: Optional[str] = None,
) -> ChatResponse:
    """
    Full RAG chain: classify → retrieve → rerank → assemble → LLM → response.
    """
    conv_id = conversation_id or str(uuid.uuid4())

    # 1. Classify query
    query_type, fetch_multiplier = classify_query(query)
    logger.info("query_classified", query_type=query_type, multiplier=fetch_multiplier)

    # 2. Compute dynamic k
    base_k = settings.retrieval_fetch_k
    fetch_k = min(int(base_k * fetch_multiplier), base_k * 2)
    final_k = settings.retrieval_k

    # 3. Retrieve
    retrieved_chunks = retrieve_for_query(
        repository_id=repository_id,
        query=query,
        k=fetch_k,
        fetch_k=fetch_k,
    )

    if not retrieved_chunks:
        return ChatResponse(
            answer="I couldn't find any relevant information in the indexed repository to answer your question. "
                   "The repository may not contain documentation or code related to your query.",
            sources=[],
            query_type=query_type,
            conversation_id=conv_id,
            repository_id=repository_id,
        )

    # 4. Rerank
    reranked = rerank(query, retrieved_chunks, top_k=final_k)

    # 5. Assemble context
    context = build_context_string(reranked)

    # 6. Build LLM messages
    messages = build_messages(
        query=query,
        context=context,
        conversation_history=conversation_history,
    )

    # 7. Call LLM
    try:
        answer = await get_llm_response(messages)
    except Exception as exc:
        logger.error("llm_call_failed", error=str(exc))
        answer = f"I retrieved relevant context from the repository, but couldn't generate an answer due to a LLM error: {exc}"

    # 8. Build sources
    sources = _build_sources(reranked, repo_url, owner, repo_name, default_branch)

    logger.info(
        "rag_chain_complete",
        repo=repository_id,
        query_type=query_type,
        chunks_retrieved=len(retrieved_chunks),
        chunks_after_rerank=len(reranked),
        sources=len(sources),
    )

    return ChatResponse(
        answer=answer,
        sources=sources,
        query_type=query_type,
        conversation_id=conv_id,
        repository_id=repository_id,
    )


async def generate_overview(
    repository_id: str,
    repo_url: str,
    owner: str,
    repo_name: str,
    default_branch: str,
) -> str:
    """Generate a comprehensive repository overview using the RAG pipeline."""
    overview_queries = [
        "project overview architecture main components",
        "installation setup requirements dependencies",
        "API endpoints routes handlers",
        "database models schema configuration",
        "authentication authorization security",
        "data flow pipeline processing",
    ]

    all_chunks = []
    seen_content = set()

    for q in overview_queries:
        chunks = retrieve_for_query(repository_id, q, k=5, fetch_k=8)
        for c in chunks:
            key = c["content"][:80]
            if key not in seen_content:
                seen_content.add(key)
                all_chunks.append(c)
        if len(all_chunks) >= 25:
            break

    if not all_chunks:
        return "Unable to generate an overview — no indexed content found."

    context = build_context_string(all_chunks[:20])
    messages = [
        {"role": "system", "content": OVERVIEW_PROMPT},
        {"role": "user", "content": f"{context}\n\nGenerate a comprehensive project overview."},
    ]

    try:
        return await get_llm_response(messages)
    except Exception as exc:
        return f"Overview generation failed: {exc}"
