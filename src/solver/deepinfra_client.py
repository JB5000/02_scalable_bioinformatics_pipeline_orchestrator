"""Thin DeepInfra chat client compatible with OpenAI-style endpoints."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List

import requests


@dataclass
class DeepInfraChatClient:
    """Simple wrapper around DeepInfra chat completions endpoint."""

    api_key: str
    model: str = "gpt-oss-120b"
    base_url: str = "https://api.deepinfra.com/v1/openai"
    timeout_seconds: int = 120

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 1800,
    ) -> str:
        """Send chat completion request and return assistant text."""
        url = f"{self.base_url.rstrip('/')}/chat/completions"
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        response = requests.post(
            url,
            headers=headers,
            data=json.dumps(payload),
            timeout=self.timeout_seconds,
        )

        if response.status_code >= 400:
            text = response.text.strip()
            raise RuntimeError(
                f"DeepInfra error {response.status_code}: {text[:800]}"
            )

        body = response.json()
        choices = body.get("choices", [])
        if not choices:
            raise RuntimeError("DeepInfra response did not include choices")

        message = choices[0].get("message", {})
        content = message.get("content", "")
        if not isinstance(content, str):
            raise RuntimeError("DeepInfra response content is not text")
        return content.strip()
