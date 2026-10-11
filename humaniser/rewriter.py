"""Rewrite a whole draft: split it, stream each piece through the model, check it, retry once.

`rewrite_events` yields plain dicts that the web server forwards as server-sent events:

    start         {"segments": [{"kind", "text" (keep only), "joiner"}], "pieces": n}
    attempt       {"index", "attempt", "reason": "first" | "language" | "retry"}
    token         {"index", "text"}
    piece_done    {"index", "text", "checks", "attempts", "chosen"}
    done          {"text", "checks", "flagged", "seconds"}
    error         {"message"}

`index` is the segment's position in `segments`; only "prose" segments go to the model.
"""

import time
from typing import AsyncIterator

from . import chunking
from .backends import Backend, BackendError, max_new_tokens
from .checks import RETRY_ISSUES, check, retry_score
from .prompt import build_prompt

LANGUAGE_RESAMPLES = 3   # the authors' rule: an English draft answered in Chinese is sampled again, up to 3 times
ISSUE_RETRIES = 1


async def _sample(backend: Backend, index: int, draft: str, out: list) -> AsyncIterator[dict]:
    text, truncated = [], False
    async for chunk in backend.stream(build_prompt(draft), max_new_tokens(draft, backend.context)):
        if chunk.text:
            text.append(chunk.text)
            yield {"type": "token", "index": index, "text": chunk.text}
        if chunk.done:
            truncated = chunk.truncated
    out.append(("".join(text).strip(), truncated))


async def rewrite_piece(backend: Backend, index: int, draft: str, retry: bool) -> AsyncIterator[dict]:
    attempts: list[tuple[str, dict]] = []
    language_resamples = issue_retries = 0
    reason = "first"
    while True:
        yield {"type": "attempt", "index": index, "attempt": len(attempts) + 1, "reason": reason}
        sampled: list = []
        async for event in _sample(backend, index, draft, sampled):
            yield event
        text, truncated = sampled[0]
        result = check(draft, text, truncated)
        attempts.append((text, result))
        if result["wrong_language"] and language_resamples < LANGUAGE_RESAMPLES:
            language_resamples += 1
            reason = "language"
        elif retry and issue_retries < ISSUE_RETRIES and any(i in RETRY_ISSUES for i in result["issues"]):
            issue_retries += 1
            reason = "retry"
        else:
            break
    best = min(range(len(attempts)), key=lambda k: retry_score(attempts[k][1]))
    text, result = attempts[best]
    yield {"type": "piece_done", "index": index, "text": text, "checks": result,
           "attempts": len(attempts), "chosen": best + 1}


async def rewrite_events(backend: Backend, draft: str, retry: bool = True) -> AsyncIterator[dict]:
    started = time.monotonic()
    segments = chunking.split(draft)
    if not segments:
        yield {"type": "error", "message": "The draft is empty."}
        return
    yield {
        "type": "start",
        "pieces": sum(s.kind == "prose" for s in segments),
        "segments": [{"kind": s.kind, "joiner": s.joiner, **({"text": s.text} if s.kind == "keep" else {})}
                     for s in segments],
    }
    outputs = [s.text if s.kind == "keep" else "" for s in segments]
    flagged = []
    try:
        for i, seg in enumerate(segments):
            if seg.kind != "prose":
                continue
            async for event in rewrite_piece(backend, i, seg.text, retry):
                if event["type"] == "piece_done":
                    outputs[i] = event["text"]
                    if any(issue in RETRY_ISSUES or issue == "language" for issue in event["checks"]["issues"]):
                        flagged.append(i)
                yield event
    except BackendError as e:
        yield {"type": "error", "message": str(e)}
        return
    text = chunking.join(segments, outputs)
    yield {"type": "done", "text": text, "checks": check(draft, text), "flagged": flagged,
           "seconds": round(time.monotonic() - started, 1)}
