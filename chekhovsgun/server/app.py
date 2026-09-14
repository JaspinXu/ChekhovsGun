"""FastAPI application — binds to localhost only, by design.

Your bookmark library and your viewing history are about as personal as data
gets, so nothing here is designed to be exposed to a network. The browser
extension reaches it at ``http://127.0.0.1:8700``; browsers treat loopback as a
secure origin, so the call works from an HTTPS page without mixed-content
warnings.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from ..config import Config, load_config
from ..engine import Engine
from ..models import Context

log = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).parent / "static"


# --------------------------------------------------------------------- schemas
class RelateRequest(BaseModel):
    source: str = ""
    source_id: str = ""
    title: str = ""
    author: str = ""
    description: str = ""
    url: str = ""
    tags: list[str] = Field(default_factory=list)
    limit: int | None = None
    explain: bool = True

    def to_context(self) -> Context:
        return Context(
            source=self.source,
            source_id=self.source_id,
            title=self.title,
            author=self.author,
            description=self.description,
            tags=self.tags,
            url=self.url,
        )


class IngestRequest(BaseModel):
    source: str = ""
    limit: int | None = None
    force: bool = False
    fetch_transcripts: bool = True


class FeedbackRequest(BaseModel):
    item_id: str = ""
    context_id: str = ""
    useful: bool = True
    note: str = ""


# ------------------------------------------------------------------- job board
class JobBoard:
    """Ingest can take minutes; the dashboard polls these records for progress."""

    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def create(self, kind: str, detail: dict[str, Any]) -> str:
        job_id = uuid.uuid4().hex[:12]
        with self._lock:
            self._jobs[job_id] = {
                "id": job_id,
                "kind": kind,
                "detail": detail,
                "state": "running",
                "started_at": time.time(),
                "finished_at": 0.0,
                "progress": {"stage": "starting", "seen": 0, "title": ""},
                "result": None,
                "error": "",
            }
        return job_id

    def update(self, job_id: str, **fields: Any) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job.update(fields)

    def progress(self, job_id: str, stage: str, payload: dict) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job["progress"] = {"stage": stage, **payload}

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: -j["started_at"])
        return jobs[:limit]


def create_app(config: Config | None = None, engine: Engine | None = None) -> FastAPI:
    config = config or load_config()
    engine = engine or Engine(config)
    jobs = JobBoard()

    app = FastAPI(
        title="ChekhovsGun",
        description="Every bookmark must fire. Local RAG over what you saved on YouTube and Bilibili.",
        version=__import__("chekhovsgun").__version__,
    )
    app.state.engine = engine
    app.state.jobs = jobs

    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.server.cors_origins,
        # Browser extensions call from chrome-extension:// and moz-extension://
        # origins whose ids are not known until the user installs the unpacked
        # extension, so they have to be matched by pattern.
        allow_origin_regex=r"^(chrome|moz)-extension://.*$"
        if config.server.allow_extension_origins
        else None,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        max_age=600,
    )

    # ------------------------------------------------------------------ pages
    @app.get("/", include_in_schema=False)
    def dashboard() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/app.css", include_in_schema=False)
    def stylesheet() -> FileResponse:
        return FileResponse(STATIC_DIR / "app.css", media_type="text/css")

    @app.get("/app.js", include_in_schema=False)
    def script() -> FileResponse:
        return FileResponse(STATIC_DIR / "app.js", media_type="application/javascript")

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, Any]:
        return {"ok": True, "version": app.version}

    # -------------------------------------------------------------------- API
    @app.get("/api/status")
    def status() -> dict[str, Any]:
        return engine.status()

    @app.get("/api/config")
    def show_config() -> dict[str, Any]:
        return config.redacted()

    @app.post("/api/relate")
    def relate(request: RelateRequest) -> dict[str, Any]:
        context = request.to_context()
        if not context.source and request.url:
            from ..adapters import detect_source

            context.source, context.source_id = detect_source(request.url)
        return engine.relate(context, limit=request.limit, explain=request.explain)

    @app.get("/api/relate")
    def relate_by_url(url: str, limit: int | None = None) -> dict[str, Any]:
        return engine.relate_url(url, limit=limit)

    @app.get("/api/search")
    def search(
        q: str = Query(..., min_length=1),
        limit: int = Query(10, ge=1, le=50),
        source: str = "",
    ) -> dict[str, Any]:
        sources = {source} if source else None
        hits = engine.search(q, limit=limit, sources=sources)
        return {"query": q, "count": len(hits), "hits": [hit.to_dict() for hit in hits]}

    @app.get("/api/items")
    def list_items(
        source: str = "",
        q: str = "",
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ) -> dict[str, Any]:
        items = engine.store.list_items(source=source, query=q, limit=limit, offset=offset)
        return {"count": len(items), "items": [item.to_dict() for item in items]}

    @app.get("/api/items/{item_id:path}")
    def get_item(item_id: str) -> dict[str, Any]:
        item = engine.store.get_item(item_id)
        if item is None:
            raise HTTPException(status_code=404, detail=f"no such item: {item_id}")
        return {
            "item": item.to_dict(),
            "chunks": [chunk.to_dict() for chunk in engine.store.item_chunks(item_id)],
        }

    @app.delete("/api/items/{item_id:path}")
    def delete_item(item_id: str) -> dict[str, Any]:
        if engine.store.get_item(item_id) is None:
            raise HTTPException(status_code=404, detail=f"no such item: {item_id}")
        engine.store.delete_item(item_id)
        engine.invalidate_cache()
        return {"deleted": item_id}

    @app.post("/api/ingest")
    def ingest(request: IngestRequest) -> dict[str, Any]:
        sources = [request.source] if request.source else None
        job_id = jobs.create("ingest", {"source": request.source or "all"})

        def worker() -> None:
            try:
                reports = []
                for adapter in engine.adapters(sources):
                    if not adapter.configured:
                        adapter.close()
                        continue
                    reports.append(
                        engine.ingest(
                            adapter,
                            limit=request.limit,
                            force=request.force,
                            fetch_transcripts=request.fetch_transcripts,
                            progress=lambda stage, payload: jobs.progress(job_id, stage, payload),
                        )
                    )
                jobs.update(
                    job_id,
                    state="done",
                    finished_at=time.time(),
                    result=[report.to_dict() for report in reports],
                )
            except Exception as exc:  # pragma: no cover - surfaced through the job
                log.exception("ingest job failed")
                jobs.update(job_id, state="failed", finished_at=time.time(), error=str(exc))

        threading.Thread(target=worker, name=f"ingest-{job_id}", daemon=True).start()
        return {"job_id": job_id, "state": "running"}

    @app.get("/api/jobs")
    def list_jobs() -> dict[str, Any]:
        return {"jobs": jobs.list()}

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="no such job")
        return job

    @app.get("/api/events")
    def events(limit: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
        return {"events": engine.store.recent_events(limit)}

    @app.post("/api/feedback")
    def feedback(request: FeedbackRequest) -> dict[str, Any]:
        engine.store.log_event(
            "feedback",
            item_id=request.item_id,
            payload={"useful": request.useful, "note": request.note, "context": request.context_id},
        )
        return {"ok": True}

    @app.exception_handler(Exception)
    async def unhandled(_request, exc: Exception) -> JSONResponse:  # pragma: no cover
        log.exception("unhandled error")
        return JSONResponse(status_code=500, content={"detail": str(exc)})

    return app


def run(config: Config | None = None, *, reload: bool = False) -> None:
    import uvicorn

    config = config or load_config()
    app = create_app(config)
    uvicorn.run(
        app,
        host=config.server.host,
        port=config.server.port,
        log_level="info",
        reload=reload,
    )
