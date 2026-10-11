"""Send ADK's spans to an OpenTelemetry exporter.

OFF BY DEFAULT, and honestly labelled, because export to Cloud Trace is
NOT verified. Read this before turning it on.

What IS verified: ADK instruments its own work, and with a provider
installed before the ADK import it emits four spans per explanation -
`invocation`, `invoke_agent field_explainer`, `call_llm`, and
`generate_content gemini-2.5-flash`. Captured with an in-memory exporter;
the instrumentation is real and the timings are there.

What is NOT verified: that those spans arrive in Cloud Trace. With
CloudTraceSpanExporter configured and force_flush returning cleanly, no
trace appeared through the v1 `traces.list` API - not from Cloud Run and
not from a direct local probe. The exporter also now emits a deprecation
warning pointing at a migration to an OTLP endpoint, so the likeliest
explanation is that the legacy write path and the legacy read API no
longer meet. Rather than claim observability we have not seen working,
the flag stays off and this note stays here.

Two real findings came out of the attempt and are worth keeping:

- Provider order matters. OpenTelemetry honours only the first
  TracerProvider set in a process and ADK builds its tracers at import
  time, so starting this from a FastAPI lifespan hook - the obvious place -
  silently produces nothing. It has to run before `import app.orchestrator`.
- Cloud Run throttles CPU to near zero between requests, so
  BatchSpanProcessor's background thread is never scheduled and spans die
  with the instance. Anything exporting from Cloud Run has to flush inside
  the request, which is what `flush()` below is for.

To pick this up later, start with the OTLP exporter against
telemetry.googleapis.com rather than this one.
"""
from __future__ import annotations

import logging
import os

from app import config

logger = logging.getLogger(__name__)

ENABLED = os.environ.get("ENABLE_TRACING", "false").lower() == "true"

_started = False
_provider = None


def start() -> bool:
    """Install the exporter. Returns whether tracing is actually on."""
    global _started
    if _started or not ENABLED or config.USE_STUB or not config.PROJECT_ID:
        return _started

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = TracerProvider(
            resource=Resource.create(
                {
                    "service.name": "snapkaki",
                    "service.version": config.PINNED_ADK,
                }
            )
        )
        provider.add_span_processor(
            BatchSpanProcessor(
                CloudTraceSpanExporter(project_id=config.PROJECT_ID),
                # Short, because the batch is flushed per request anyway
                # (see flush below) - this is only the backstop.
                schedule_delay_millis=2000,
            )
        )
        trace.set_tracer_provider(provider)
        _provider = provider
        _started = True
        logger.info("Cloud Trace enabled for project %s", config.PROJECT_ID)
    except Exception:
        # A missing API, a missing role, a version skew - none of it is
        # worth failing a request over.
        logger.exception("tracing setup failed; continuing without it")

    return _started


def active() -> bool:
    """Whether spans are actually being exported."""
    return _started


def flush(timeout_ms: int = 2000) -> None:
    """Push pending spans out before the request ends.

    This is what makes tracing work on Cloud Run at all. CPU is throttled
    to near zero between requests, so BatchSpanProcessor's background
    export thread is never scheduled and the spans simply die with the
    instance - the exporter installs cleanly, reports success, and sends
    nothing. Flushing while the request is still in flight is the moment
    CPU is actually allocated.

    The alternative is --no-cpu-throttling, which bills for idle instances
    across a three-week evaluation window for no user-visible benefit.
    """
    if not _started or _provider is None:
        return
    try:
        _provider.force_flush(timeout_ms)
    except Exception:
        logger.debug("span flush failed", exc_info=True)
