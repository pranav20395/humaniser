"""Clients for the servers that run the model.

- LlamaCppBackend: llama.cpp's `llama-server`, native `/completion` endpoint
  (recommended by the model's authors; works with every GGUF download).
- OpenAICompatBackend: any OpenAI-style `/v1/completions` server, such as
  vLLM (`--generation-config vllm`) or LM Studio. Never `/v1/chat/completions`.

Both send the raw prompt with the model's sampling settings and stream tokens.
"""

import json
import math
import re
from dataclasses import dataclass
from typing import AsyncIterator

import httpx

from .checks import CJK
from .prompt import CONTEXT_TOKENS, SAMPLING

PROMPT_OVERHEAD_TOKENS = 100   # the instruction and separator


class BackendError(Exception):
    pass


@dataclass
class Chunk:
    text: str = ""
    done: bool = False
    truncated: bool = False     # stopped at the token limit instead of EOS


def estimate_tokens(text: str) -> int:
    """Rough token count without a tokenizer: one per CJK character, ~3.2 characters otherwise."""
    cjk = len(CJK.findall(text))
    return cjk + math.ceil((len(text) - cjk) / 3.2)


def max_new_tokens(draft: str, context: int = CONTEXT_TOKENS) -> int:
    """About 2.5x the draft, between 256 and 2048 (the authors' app rule), within the context."""
    n = estimate_tokens(draft)
    room = context - n - PROMPT_OVERHEAD_TOKENS - 16
    return max(64, min(max(256, math.ceil(n * 2.5)), 2048, room))


async def _sse_events(response: httpx.Response) -> AsyncIterator[str]:
    async for line in response.aiter_lines():
        if line.startswith("data:"):
            yield line[5:].strip()


async def _raise_for_status(response: httpx.Response) -> None:
    if response.status_code >= 400:
        body = (await response.aread()).decode("utf-8", "replace")
        try:
            body = json.loads(body).get("error", body)
            if isinstance(body, dict):
                body = body.get("message", body)
        except (ValueError, AttributeError):
            pass
        raise BackendError(f"{response.request.url.path} returned {response.status_code}: {str(body)[:300]}")


class Backend:
    kind = "base"

    def __init__(self, url: str, client: httpx.AsyncClient | None = None, context: int = CONTEXT_TOKENS):
        self.url = url.rstrip("/")
        self.context = context
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=1800.0))

    async def aclose(self) -> None:
        await self.client.aclose()

    async def health(self) -> dict:
        raise NotImplementedError

    def stream(self, prompt: str, max_tokens: int) -> AsyncIterator[Chunk]:
        raise NotImplementedError


class LlamaCppBackend(Backend):
    kind = "llama.cpp"

    async def health(self) -> dict:
        try:
            r = await self.client.get(self.url + "/health", timeout=5.0)
        except httpx.HTTPError as e:
            return {"status": "offline", "detail": f"cannot reach llama-server at {self.url} ({type(e).__name__})"}
        if r.status_code == 503:
            return {"status": "loading", "detail": "llama-server is loading the model"}
        if r.status_code != 200:
            return {"status": "error", "detail": f"/health returned {r.status_code}"}
        info = {"status": "ready", "detail": "llama-server is ready"}
        try:
            props = (await self.client.get(self.url + "/props", timeout=5.0)).json()
            path = props.get("model_path") or ""
            info["model"] = re.split(r"[\\/]", path)[-1] or None
            n_ctx = (props.get("default_generation_settings") or {}).get("n_ctx")
            if n_ctx:
                # Per-slot context: with -np N the server splits -c across N slots.
                info["context"] = self.context = n_ctx
        except (httpx.HTTPError, ValueError):
            pass
        return info

    async def stream(self, prompt: str, max_tokens: int) -> AsyncIterator[Chunk]:
        body = {"prompt": prompt, "n_predict": max_tokens, "stream": True, "cache_prompt": True, **SAMPLING}
        try:
            async with self.client.stream("POST", self.url + "/completion", json=body) as r:
                await _raise_for_status(r)
                async for data in _sse_events(r):
                    event = json.loads(data)
                    if "error" in event:
                        raise BackendError(str(event["error"].get("message", event["error"])))
                    if event.get("stop"):
                        truncated = event.get("stop_type") == "limit" or bool(event.get("truncated"))
                        yield Chunk(event.get("content", ""), done=True, truncated=truncated)
                        return
                    if event.get("content"):
                        yield Chunk(event["content"])
        except httpx.HTTPError as e:
            raise BackendError(f"llama-server request failed: {type(e).__name__}: {e}") from e
        yield Chunk(done=True)


class OpenAICompatBackend(Backend):
    kind = "openai"

    def __init__(self, url: str, model: str | None = None, api_key: str | None = None, **kw):
        super().__init__(url, **kw)
        self.model = model
        self.headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        if self.url.endswith("/v1"):
            self.url = self.url[:-3]

    async def health(self) -> dict:
        try:
            r = await self.client.get(self.url + "/v1/models", headers=self.headers, timeout=5.0)
        except httpx.HTTPError as e:
            return {"status": "offline", "detail": f"cannot reach {self.url} ({type(e).__name__})"}
        if r.status_code != 200:
            return {"status": "error", "detail": f"/v1/models returned {r.status_code}"}
        try:
            ids = [m["id"] for m in r.json().get("data", [])]
        except (ValueError, KeyError, TypeError):
            ids = []
        if not self.model and ids:
            self.model = ids[0]
        return {"status": "ready", "detail": "server is ready", "model": self.model}

    async def stream(self, prompt: str, max_tokens: int) -> AsyncIterator[Chunk]:
        body = {
            "model": self.model or "humanizer", "prompt": prompt, "max_tokens": max_tokens, "stream": True,
            # LM Studio reads repeat_penalty, vLLM repetition_penalty.
            **SAMPLING, "repetition_penalty": SAMPLING["repeat_penalty"],
        }
        try:
            async with self.client.stream("POST", self.url + "/v1/completions", json=body,
                                          headers=self.headers) as r:
                await _raise_for_status(r)
                async for data in _sse_events(r):
                    if data == "[DONE]":
                        break
                    event = json.loads(data)
                    if "error" in event:
                        raise BackendError(str(event["error"]))
                    choice = (event.get("choices") or [{}])[0]
                    if choice.get("text"):
                        yield Chunk(choice["text"])
                    if choice.get("finish_reason"):
                        yield Chunk(done=True, truncated=choice["finish_reason"] == "length")
                        return
        except httpx.HTTPError as e:
            raise BackendError(f"request to {self.url} failed: {type(e).__name__}: {e}") from e
        yield Chunk(done=True)


def make_backend(kind: str, url: str, model: str | None = None, api_key: str | None = None) -> Backend:
    if kind == "llama.cpp":
        return LlamaCppBackend(url)
    if kind == "openai":
        return OpenAICompatBackend(url, model=model, api_key=api_key)
    raise ValueError(f"unknown backend {kind!r}")
