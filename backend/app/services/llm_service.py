from __future__ import annotations

from typing import List, Optional

import requests

from app.core.config import get_settings


class LLMServiceError(RuntimeError):
    pass


def _normalize_base_url(url: str) -> str:
    base = (url or "").rstrip("/")
    if not base:
        return ""
    return base


def chat_completion(messages: List[dict], model: Optional[str] = None, timeout_seconds: float = 20.0) -> Optional[str]:
    settings = get_settings()
    api_key = settings.openai_api_key
    base_url = _normalize_base_url(settings.openai_base_url)
    if not api_key or not base_url:
        return None

    url = f"{base_url}/v1/chat/completions"
    payload = {
        "model": model or settings.openai_model,
        "messages": messages,
        "temperature": 0.2,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    response = requests.post(url, json=payload, headers=headers, timeout=timeout_seconds)
    response.raise_for_status()
    data = response.json()
    choices = data.get("choices") or []
    if not choices:
        return None
    message = choices[0].get("message") or {}
    content = message.get("content")
    if not content:
        return None
    return str(content).strip()
