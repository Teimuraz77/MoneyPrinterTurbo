"""Tiny Ollama client (local, self-hosted). Structured JSON output via ``format=<schema>``."""

from __future__ import annotations

import json
import time

import requests
from loguru import logger

from wwnn.util import StageError


class OllamaClient:
    def __init__(self, base_url: str, model: str, timeout_s: float = 600.0, temperature: float = 0.8):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_s = timeout_s
        self.temperature = temperature

    def chat_json(self, system: str, user: str, schema: dict, *, model: str | None = None,
                  temperature: float | None = None, retries: int = 2) -> dict:
        payload = {
            "model": model or self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "format": schema,
            "stream": False,
            "keep_alive": 0,          # unload right after: the GPU is needed by TTS/LongCat next
            "think": False,           # ignored by non-thinking models; disables qwen3-style reasoning
            "options": {"temperature": self.temperature if temperature is None else temperature,
                        "num_ctx": 16384},
        }
        last: Exception | None = None
        for attempt in range(retries + 1):
            try:
                r = requests.post(f"{self.base_url}/api/chat", json=payload, timeout=self.timeout_s)
                if r.status_code == 400 and "think" in r.text:
                    payload.pop("think", None)
                    r = requests.post(f"{self.base_url}/api/chat", json=payload, timeout=self.timeout_s)
                r.raise_for_status()
                content = r.json()["message"]["content"]
                return json.loads(content)
            except (requests.RequestException, KeyError, json.JSONDecodeError) as e:
                last = e
                logger.warning(f"ollama call failed (attempt {attempt + 1}): {e}")
                time.sleep(2 * (attempt + 1))
        raise StageError(f"Ollama request failed: {last}")

    def available(self) -> bool:
        try:
            return requests.get(f"{self.base_url}/api/tags", timeout=5).ok
        except requests.RequestException:
            return False

    def unload_all(self) -> None:
        """Free VRAM before a GPU stage: ask Ollama to unload every loaded model."""
        try:
            loaded = requests.get(f"{self.base_url}/api/ps", timeout=10).json().get("models", [])
            for m in loaded:
                requests.post(f"{self.base_url}/api/generate",
                              json={"model": m["name"], "keep_alive": 0}, timeout=30)
                logger.info(f"unloaded ollama model {m['name']}")
        except requests.RequestException as e:
            logger.debug(f"ollama unload skipped: {e}")
