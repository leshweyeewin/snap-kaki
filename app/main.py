"""FastAPI entry point. Two endpoints plus static hosting for the web app.

    POST /session   -> start a session, pick a language
    POST /turn      -> one interaction (scan | ask | done | next | family)

/turn is multipart so the camera can post an image on the same path as a
text turn. The frontend is served from the same origin, which keeps
getUserMedia happy without a CORS dance.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import config, orchestrator
from app.session import store

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
logger = logging.getLogger("snapkaki")

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

# Cloud Run's request limit is 32 MiB; a phone camera JPEG is ~2-5 MB. Cap
# well below the platform limit so an oversized upload fails fast with a
# clear message instead of being cut off mid-stream.
MAX_IMAGE_BYTES = 8 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic"}

@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Log the wiring once. A Cloud Run rebuild that drifts to a new ADK
    major should be visible here rather than as a mystery 500."""
    import importlib.metadata as meta

    def _version(pkg: str) -> str:
        try:
            return meta.version(pkg)
        except Exception:
            return "missing"

    adk, genai = _version("google-adk"), _version("google-genai")
    logger.info(
        "SnapKaki starting: project=%s location=%s model=%s stub=%s floor=%.2f",
        config.PROJECT_ID, config.LOCATION, config.GEMINI_MODEL,
        config.USE_STUB, config.CONFIDENCE_FLOOR,
    )
    logger.info(
        "google-adk=%s (pinned %s)  google-genai=%s (pinned %s)",
        adk, config.PINNED_ADK, genai, config.PINNED_GENAI,
    )
    if adk != config.PINNED_ADK or genai != config.PINNED_GENAI:
        logger.warning(
            "Dependency drift from the verified pins. If agents misbehave, "
            "check requirements.txt before debugging the prompts."
        )
    yield


app = FastAPI(title="SnapKaki", version="0.1.0", lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True, "stub": config.USE_STUB, "model": config.GEMINI_MODEL}


@app.post("/session")
async def create_session(language: str = Form(config.DEFAULT_LANGUAGE)) -> JSONResponse:
    """Start a session. Returns the id the client sends back on every turn."""
    session = store.create(language=language)
    logger.info("session %s created (language=%s)", session.session_id, session.language)
    return JSONResponse(
        {
            "session_id": session.session_id,
            "language": session.language,
            "languages": config.SUPPORTED_LANGUAGES,
            "form_id": session.form_id,
        }
    )


@app.post("/turn")
async def turn(
    session_id: str = Form(...),
    kind: str = Form(...),
    field_label: Optional[str] = Form(None),
    question: Optional[str] = Form(None),
    reason: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
) -> JSONResponse:
    """One interaction.

    kind:
      scan   - an image is attached; read the form and give the next step
      ask    - explain field_label, optionally answering `question`
      done   - the user finished field_label; give the next step
      next   - just give the next step
      family - draft the message asking a relative for help
    """
    session = store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found; start a new one")

    kind = (kind or "").strip().lower()

    if kind == "scan":
        if image is None:
            raise HTTPException(status_code=400, detail="scan turn needs an image")
        content_type = (image.content_type or "").lower()
        if content_type not in ALLOWED_IMAGE_TYPES:
            raise HTTPException(
                status_code=415,
                detail=f"unsupported image type {content_type or 'unknown'}",
            )
        data = await image.read()
        if not data:
            raise HTTPException(status_code=400, detail="empty image")
        if len(data) > MAX_IMAGE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"image is {len(data) // 1024}KB; keep it under "
                       f"{MAX_IMAGE_BYTES // 1024}KB",
            )
        logger.info("session %s scan: %d bytes %s", session_id, len(data), content_type)
        result = await orchestrator.handle_scan(session, data, image_mime=content_type)

    elif kind == "ask":
        if not field_label:
            raise HTTPException(status_code=400, detail="ask turn needs field_label")
        result = await orchestrator.handle_question(
            session, field_label=field_label, question=question or ""
        )

    elif kind == "done":
        if not field_label:
            raise HTTPException(status_code=400, detail="done turn needs field_label")
        result = await orchestrator.handle_field_done(session, field_label=field_label)

    elif kind == "next":
        result = await orchestrator.handle_next(session)

    elif kind == "family":
        result = await orchestrator.handle_family_loop(
            session, stuck_on=field_label or "", reason=reason or ""
        )

    else:
        raise HTTPException(status_code=400, detail=f"unknown turn kind {kind!r}")

    return JSONResponse(result.to_dict())


# --- static web app --------------------------------------------------------
# Mounted last so the API routes above win on a path collision.

if WEB_DIR.is_dir():
    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")

    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
else:  # pragma: no cover - only hit if the image was built without web/
    logger.warning("web/ not found at %s; serving API only", WEB_DIR)
