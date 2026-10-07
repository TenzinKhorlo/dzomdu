"""Minimal chat client for local LLM servers.

* api = "ollama": Ollama's native /api/chat. Lets us set num_ctx (the OpenAI-compatible
  endpoint can't, and Ollama's small default context silently truncates long transcripts)
  and constrain output with a JSON schema.
* api = "openai": any OpenAI-compatible server (mlx-lm, LM Studio, vLLM, llama.cpp).
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from ..config import LLMConfig


class LLMError(RuntimeError):
    pass


_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json(text: str) -> Any:
    """Parse JSON from a model reply, tolerating <think> blocks, code fences and prose."""
    text = _THINK.sub("", text).strip()
    candidates = [text]
    candidates += [m.strip() for m in _FENCE.findall(text)]
    start = text.find("{")
    if start != -1:
        candidates.append(_balanced_object(text, start))
    for cand in candidates:
        if not cand:
            continue
        try:
            return json.loads(cand)
        except json.JSONDecodeError:
            continue
    raise LLMError(f"Model did not return valid JSON: {text[:300]!r}")


def _balanced_object(text: str, start: int) -> str:
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return text[start:]


class LLMClient:
    def __init__(self, cfg: LLMConfig, http: httpx.Client | None = None):
        self.cfg = cfg
        headers = {"Authorization": f"Bearer {cfg.api_key}"} if cfg.api_key else {}
        self.http = http or httpx.Client(timeout=cfg.timeout, headers=headers)

    @property
    def model(self) -> str:
        return self.cfg.model

    def chat(self, messages: list[dict[str, str]], schema: dict[str, Any] | None = None) -> str:
        if self.cfg.api == "ollama":
            return self._ollama(messages, schema)
        if self.cfg.api == "openai":
            return self._openai(messages, schema)
        raise LLMError(f"Unknown llm.api {self.cfg.api!r} (use 'ollama' or 'openai')")

    def chat_json(
        self, system: str, user: str, schema: dict[str, Any], retries: int = 1
    ) -> dict[str, Any]:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        last_error: Exception | None = None
        for _ in range(retries + 1):
            reply = self.chat(messages, schema)
            try:
                data = extract_json(reply)
                if isinstance(data, dict):
                    return data
                last_error = LLMError("Expected a JSON object")
            except LLMError as exc:
                last_error = exc
            messages = messages + [
                {"role": "assistant", "content": reply},
                {
                    "role": "user",
                    "content": "That was not valid JSON. Reply with only the JSON "
                    "object matching the schema.",
                },
            ]
        raise LLMError(str(last_error))

    # -- backends ---------------------------------------------------------------------------

    def _url(self, path: str) -> str:
        return self.cfg.base_url.rstrip("/") + path

    def _post(self, url: str, payload: dict[str, Any]) -> httpx.Response:
        try:
            return self.http.post(url, json=payload)
        except httpx.HTTPError as exc:
            raise LLMError(f"Cannot reach the LLM server at {self.cfg.base_url}: {exc}") from exc

    def _ollama(self, messages: list[dict[str, str]], schema: dict[str, Any] | None) -> str:
        payload: dict[str, Any] = {
            "model": self.cfg.model,
            "messages": messages,
            "stream": False,
            "keep_alive": self.cfg.keep_alive,
            "options": {"temperature": self.cfg.temperature, "num_ctx": self.cfg.num_ctx},
        }
        if schema is not None:
            payload["format"] = schema
        if self.cfg.think is not None:
            payload["think"] = self.cfg.think
        resp = self._post(self._url("/api/chat"), payload)
        if resp.status_code == 400 and "think" in payload and "think" in resp.text.lower():
            payload.pop("think")  # model doesn't support the think flag
            resp = self._post(self._url("/api/chat"), payload)
        if resp.status_code != 200:
            raise LLMError(f"Ollama error {resp.status_code}: {resp.text[:300]}")
        return resp.json()["message"]["content"]

    def _openai(self, messages: list[dict[str, str]], schema: dict[str, Any] | None) -> str:
        base = self.cfg.base_url.rstrip("/")
        url = base + ("/chat/completions" if base.endswith("/v1") else "/v1/chat/completions")
        payload: dict[str, Any] = {
            "model": self.cfg.model,
            "messages": messages,
            "temperature": self.cfg.temperature,
        }
        if schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "meeting_notes", "schema": schema},
            }
        resp = self._post(url, payload)
        if resp.status_code == 400 and schema is not None:
            # server doesn't support json_schema: fall back to plain JSON mode, then to prose
            payload["response_format"] = {"type": "json_object"}
            resp = self._post(url, payload)
            if resp.status_code == 400:
                payload.pop("response_format")
                resp = self._post(url, payload)
        if resp.status_code != 200:
            raise LLMError(f"LLM server error {resp.status_code}: {resp.text[:300]}")
        return resp.json()["choices"][0]["message"]["content"]

    def ping(self) -> tuple[bool, str]:
        """Check the server is up and the model is available."""
        try:
            if self.cfg.api == "ollama":
                resp = self.http.get(self._url("/api/tags"), timeout=5)
                names = {m["name"] for m in resp.json().get("models", [])}
                wanted = self.cfg.model if ":" in self.cfg.model else f"{self.cfg.model}:latest"
                if wanted not in names:
                    return (
                        False,
                        f"model {self.cfg.model} not pulled (run: ollama pull {self.cfg.model})",
                    )
                return True, f"{self.cfg.model} available"
            base = self.cfg.base_url.rstrip("/")
            resp = self.http.get(
                base + ("/models" if base.endswith("/v1") else "/v1/models"), timeout=5
            )
            return resp.status_code == 200, f"HTTP {resp.status_code}"
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            return False, f"not reachable at {self.cfg.base_url} ({exc.__class__.__name__})"
