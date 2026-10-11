import json

import httpx
import pytest

from humaniser.backends import BackendError, LlamaCppBackend, OpenAICompatBackend, max_new_tokens
from humaniser.prompt import SAMPLING


def sse(*events):
    return "".join(f"data: {e if isinstance(e, str) else json.dumps(e)}\n\n" for e in events)


async def collect(backend, prompt="p", n=100):
    return [c async for c in backend.stream(prompt, n)]


def test_max_new_tokens_bounds():
    assert max_new_tokens("short") == 256
    assert max_new_tokens("word " * 3000) == 2048
    assert max_new_tokens("word " * 3000, context=4096) < 2048


@pytest.mark.asyncio
async def test_llamacpp_stream_sends_model_settings_and_parses_tokens():
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, text=sse({"content": "Hel", "stop": False}, {"content": "lo", "stop": False},
                                            {"content": "", "stop": True, "stop_type": "limit"}))

    backend = LlamaCppBackend("http://x", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    chunks = await collect(backend)
    assert "".join(c.text for c in chunks) == "Hello"
    assert chunks[-1].done and chunks[-1].truncated
    assert seen["path"] == "/completion"
    body = seen["body"]
    assert body["n_predict"] == 100 and body["stream"] is True and "stop" not in body
    assert {k: body[k] for k in SAMPLING} == SAMPLING


@pytest.mark.asyncio
async def test_llamacpp_http_error_is_reported():
    backend = LlamaCppBackend("http://x", client=httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(500, json={"error": {"message": "boom"}}))))
    with pytest.raises(BackendError, match="boom"):
        await collect(backend)


@pytest.mark.asyncio
async def test_llamacpp_health_states():
    def handler(request):
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(200, json={"model_path": "/m/humanizer-12b-Q4_K_M.gguf",
                                         "default_generation_settings": {"n_ctx": 4096}})

    backend = LlamaCppBackend("http://x", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    info = await backend.health()
    assert info["status"] == "ready" and info["model"] == "humanizer-12b-Q4_K_M.gguf"
    assert backend.context == 4096

    loading = LlamaCppBackend("http://x", client=httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(503, json={}))))
    assert (await loading.health())["status"] == "loading"

    def refuse(request):
        raise httpx.ConnectError("refused")

    offline = LlamaCppBackend("http://x", client=httpx.AsyncClient(transport=httpx.MockTransport(refuse)))
    assert (await offline.health())["status"] == "offline"


@pytest.mark.asyncio
async def test_openai_compat_stream():
    seen = {}

    def handler(request):
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "humanizer-12b"}]})
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, text=sse({"choices": [{"text": "Hi", "finish_reason": None}]},
                                            {"choices": [{"text": " there", "finish_reason": "stop"}]}, "[DONE]"))

    backend = OpenAICompatBackend("http://x/v1", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert (await backend.health())["model"] == "humanizer-12b"
    chunks = await collect(backend)
    assert "".join(c.text for c in chunks) == "Hi there"
    assert chunks[-1].done and not chunks[-1].truncated
    assert seen["path"] == "/v1/completions"
    assert seen["body"]["model"] == "humanizer-12b" and seen["body"]["top_k"] == 0
