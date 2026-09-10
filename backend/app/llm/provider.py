"""
LLM abstraction layer.
Supports: Ollama, OpenAI-compatible APIs.
Add new providers here without changing the rest of the codebase.
"""

from __future__ import annotations

from typing import Any, Dict, List

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


class LLMProviderError(Exception):
    """Raised when the LLM provider is unavailable or returns an error."""


# ── Ollama provider ────────────────────────────────────────────────────────────

async def _call_ollama(messages: List[Dict[str, str]]) -> str:
    import httpx

    payload = {
        "model": settings.llm_model,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_predict": 2048,
        },
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            response = await client.post(
                f"{settings.ollama_base_url}/api/chat",
                json=payload,
            )
        except httpx.ConnectError:
            raise LLMProviderError(
                f"Cannot connect to Ollama at {settings.ollama_base_url}. "
                "Make sure Ollama is running: `ollama serve`"
            )
        except httpx.TimeoutException:
            raise LLMProviderError("Ollama request timed out. The model may be loading — try again.")

        if response.status_code == 404:
            raise LLMProviderError(
                f"Ollama model '{settings.llm_model}' not found. "
                f"Pull it first: `ollama pull {settings.llm_model}`"
            )
        if response.status_code != 200:
            raise LLMProviderError(
                f"Ollama returned {response.status_code}: {response.text[:300]}"
            )

        data = response.json()
        content = data.get("message", {}).get("content", "")
        if not content:
            raise LLMProviderError("Ollama returned an empty response.")
        return content


# ── OpenAI provider ────────────────────────────────────────────────────────────

async def _call_openai(messages: List[Dict[str, str]]) -> str:
    try:
        from openai import AsyncOpenAI
    except ImportError:
        raise LLMProviderError("openai package not installed. Run: pip install openai")

    if not settings.openai_api_key:
        raise LLMProviderError("OPENAI_API_KEY is not set in .env")

    client = AsyncOpenAI(api_key=settings.openai_api_key)

    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=messages,  # type: ignore[arg-type]
            temperature=0.1,
            max_tokens=2048,
        )
        content = response.choices[0].message.content
        return content or ""
    except Exception as exc:
        raise LLMProviderError(f"OpenAI API error: {exc}") from exc


# ── Public interface ───────────────────────────────────────────────────────────

async def get_llm_response(messages: List[Dict[str, str]]) -> str:
    """
    Send messages to the configured LLM provider and return the response text.
    Raises LLMProviderError on failure.
    """
    provider = settings.llm_provider.lower()
    logger.info("llm_request", provider=provider, model=settings.llm_model, messages=len(messages))

    if provider == "ollama":
        result = await _call_ollama(messages)
    elif provider == "openai":
        result = await _call_openai(messages)
    else:
        raise LLMProviderError(
            f"Unknown LLM provider: '{provider}'. "
            "Supported: ollama, openai"
        )

    logger.info("llm_response_received", length=len(result))
    return result


async def check_llm_health() -> Dict[str, Any]:
    """Check if the configured LLM is reachable."""
    provider = settings.llm_provider.lower()
    try:
        if provider == "ollama":
            import httpx
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{settings.ollama_base_url}/api/tags")
                models = [m["name"] for m in resp.json().get("models", [])]
                available = settings.llm_model in models or any(
                    settings.llm_model.split(":")[0] in m for m in models
                )
                return {
                    "provider": "ollama",
                    "model": settings.llm_model,
                    "reachable": True,
                    "model_available": available,
                    "available_models": models,
                }
        elif provider == "openai":
            return {
                "provider": "openai",
                "model": settings.openai_model,
                "reachable": bool(settings.openai_api_key),
                "model_available": True,
            }
    except Exception as exc:
        return {
            "provider": provider,
            "reachable": False,
            "error": str(exc),
        }
    return {"provider": provider, "reachable": False}
