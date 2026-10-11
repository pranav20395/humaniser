"""Web interface: serves the page and streams rewrites as server-sent events."""

import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .backends import Backend
from .launcher import LlamaServerProcess
from .rewriter import rewrite_events

STATIC = Path(__file__).parent / "static"
MAX_DRAFT_CHARS = 200_000


class RewriteRequest(BaseModel):
    text: str = Field(max_length=MAX_DRAFT_CHARS)
    retry: bool = True


def create_app(backend: Backend, process: LlamaServerProcess | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        await backend.aclose()
        if process:
            process.stop()

    app = FastAPI(title="Humaniser", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/api/health")
    async def health():
        info = await backend.health()
        if process and info["status"] == "offline":
            if process.running():
                info = {"status": "loading", "detail": "starting llama-server"}
            else:
                info["detail"] = f"llama-server exited with code {process.returncode()}; see the terminal log"
        return {"backend": backend.kind, "url": backend.url, **info}

    @app.post("/api/rewrite")
    async def rewrite(req: RewriteRequest):
        if not req.text.strip():
            return JSONResponse({"error": "The draft is empty."}, status_code=400)

        async def events():
            async for event in rewrite_events(backend, req.text, retry=req.retry):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return app
