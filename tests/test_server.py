import json

import pytest
from fastapi.testclient import TestClient

from humaniser.backends import Backend, BackendError, Chunk
from humaniser.prompt import SEP
from humaniser.rewriter import rewrite_events
from humaniser.server import create_app


class FakeBackend(Backend):
    """Answers each request with the next scripted reply; records the prompts."""

    kind = "fake"

    def __init__(self, replies):
        super().__init__("http://fake")
        self.replies = list(replies)
        self.prompts = []

    async def health(self):
        return {"status": "ready", "detail": "ok", "model": "fake.gguf"}

    async def stream(self, prompt, max_tokens):
        self.prompts.append(prompt)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        for word in reply.split(" "):
            yield Chunk(word + " ")
        yield Chunk(done=True)


async def run(backend, draft, retry=True):
    return [e async for e in rewrite_events(backend, draft, retry=retry)]


@pytest.mark.asyncio
async def test_single_piece_rewrite():
    backend = FakeBackend(["Twelve files remain, due March 14."])
    events = await run(backend, "There are 12 files remaining. The deadline is March 14.")
    assert [e["type"] for e in events][:2] == ["start", "attempt"]
    assert events[-1]["type"] == "done"
    assert events[-1]["text"] == "Twelve files remain, due March 14."
    assert events[-1]["flagged"] == []
    assert backend.prompts[0].endswith("The deadline is March 14." + SEP)


@pytest.mark.asyncio
async def test_wrong_language_is_resampled():
    backend = FakeBackend(["请今天部署这个修复版本好吗", "Ship the fix today."])
    events = await run(backend, "Please deploy the fix today.")
    attempts = [e for e in events if e["type"] == "attempt"]
    assert [a["reason"] for a in attempts] == ["first", "language"]
    assert events[-1]["text"] == "Ship the fix today."


@pytest.mark.asyncio
async def test_failed_check_retries_once_and_keeps_the_better_try():
    backend = FakeBackend(["The deadline is soon.", "Still vague.", "never used"])
    events = await run(backend, "The deadline is March 14.")
    done = next(e for e in events if e["type"] == "piece_done")
    assert done["attempts"] == 2
    assert done["checks"]["missing_numbers"] == ["14"]
    assert events[-1]["flagged"] == [0]

    backend = FakeBackend(["The deadline is soon.", "Due March 14."])
    events = await run(backend, "The deadline is March 14.")
    done = next(e for e in events if e["type"] == "piece_done")
    assert (done["attempts"], done["chosen"], done["text"]) == (2, 2, "Due March 14.")

    backend = FakeBackend(["The deadline is soon."])
    events = await run(backend, "The deadline is March 14.", retry=False)
    assert next(e for e in events if e["type"] == "piece_done")["attempts"] == 1


@pytest.mark.asyncio
async def test_headings_are_kept_and_pieces_rejoined():
    backend = FakeBackend(["Rewritten intro.", "Rewritten body."])
    draft = "# Title\n\nIntro text.\n\n```\ncode\n```\n\nBody text."
    events = await run(backend, draft)
    assert events[0]["pieces"] == 2
    assert events[-1]["text"] == "# Title\n\nRewritten intro.\n\n```\ncode\n```\n\nRewritten body."
    assert len(backend.prompts) == 2


@pytest.mark.asyncio
async def test_backend_error_becomes_error_event():
    events = await run(FakeBackend([BackendError("llama-server went away")]), "Hello there.")
    assert events[-1] == {"type": "error", "message": "llama-server went away"}


def test_http_endpoints():
    client = TestClient(create_app(FakeBackend(["Done by 5 pm."])))
    assert "Humaniser" in client.get("/").text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/api/health").json()["status"] == "ready"
    assert client.post("/api/rewrite", json={"text": "   "}).status_code == 400

    with client.stream("POST", "/api/rewrite", json={"text": "Finish it by 5 pm."}) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        events = [json.loads(line[5:]) for line in r.iter_lines() if line.startswith("data:")]
    assert events[-1]["type"] == "done" and events[-1]["text"] == "Done by 5 pm."
