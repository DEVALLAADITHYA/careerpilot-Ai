"""Groq chat-completions client (OpenAI-compatible endpoint) with tool calling."""
from __future__ import annotations

import json
import logging

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


class LLMError(RuntimeError):
    pass


def llm_available() -> bool:
    return bool(get_settings().groq_api_key)


async def _post(body: dict, client: httpx.AsyncClient | None = None) -> dict:
    s = get_settings()
    if not s.groq_api_key:
        raise LLMError("GROQ_API_KEY is not configured")
    own = client is None
    client = client or httpx.AsyncClient(timeout=45)
    try:
        r = await client.post(GROQ_URL, json={"model": s.groq_model, **body},
                              headers={"Authorization": f"Bearer {s.groq_api_key}"})
        if r.status_code != 200:
            raise LLMError(f"Groq returned HTTP {r.status_code}")
        return r.json()
    except httpx.HTTPError as e:
        raise LLMError(f"Groq request failed: {type(e).__name__}") from e
    finally:
        if own:
            await client.aclose()


async def chat_tool(system: str, user: str, tool: dict, client=None) -> dict:
    """Force a single function/tool call and return its parsed arguments."""
    data = await _post({
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "tools": [tool], "tool_choice": {"type": "function", "function": {"name": tool["function"]["name"]}},
        "temperature": 0}, client)
    try:
        return json.loads(data["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"])
    except (KeyError, IndexError, ValueError, TypeError) as e:
        raise LLMError("Malformed tool-call response") from e


async def chat_json(system: str, user: str, client=None) -> dict:
    data = await _post({
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "response_format": {"type": "json_object"}, "temperature": 0.3}, client)
    try:
        return json.loads(data["choices"][0]["message"]["content"])
    except (KeyError, IndexError, ValueError, TypeError) as e:
        raise LLMError("Malformed JSON response") from e
