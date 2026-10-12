"""Send ADK's spans to Cloud Trace.

Verified from production on 2026-10-13. A real POST /turn through Firebase
Hosting to Cloud Run lands five spans in Cloud Trace, grouped under the
request and each with its own duration:

    3611 ms  POST /turn
    1854 ms    invocation
    1843 ms      invoke_agent guidance
    1775 ms        call_llm
    1772 ms          generate_content gemini-2.5-flash

That is the per-stage breakdown, and it is the only way to answer "which
part of the wait is the model" without guessing. On that request the answer
was half of it: the scan had hit the vision cache, so the other 1.7s was
retrieval and transport.

This file previously said export did NOT work and was turned off for that
reason. It was wrong, and the cause was here: `start()` declared only
`global _started`, so `_provider = provider` bound a local and the
module-level `_provider` stayed None. `flush()` tested `_provider is None`
and returned immediately - every time, silently. Nothing was ever flushed,
so on Cloud Run nothing was ever exported, and the conclusion drawn from
that was "the legacy write path and read API no longer meet". There was no
problem with Cloud Trace.

The fix is not to add the missing `global`. It is to stop keeping a second
copy of something OpenTelemetry already holds: `flush()` now asks
`get_tracer_provider()` for the provider that is actually installed. One
piece of state instead of two, and no way for the two to disagree. It is
also the more correct thing to flush - per the note below, the provider we
built is not necessarily the one that won.

Two findings from the original attempt, both still true and both still
load-bearing:

- Provider order matters. OpenTelemetry honours only the first
  TracerProvider set in a process and ADK builds its tracers at import
  time, so starting this from a FastAPI lifespan hook - the obvious place -
  silently produces nothing. It has to run before `import app.orchestrator`.
- Cloud Run throttles CPU to near zero between requests, so
  BatchSpanProcessor's background thread is never scheduled and spans die
  with the instance. Anything exporting from Cloud Run has to flush inside
  the request, which is what `flush()` is for.

Two operational traps, both of which make working export look broken:

- `traces.get` returns an empty span list for a few seconds after a write,
  so reading a trace back immediately looks exactly like a failure. Retry
  before concluding anything.
- The v1 `traces.list` API returns nothing at all, even for windows where
  `traces.get` on a known id returns the spans. Listing recent traces is
  therefore not a test of anything. This is what the original misdiagnosis
  was built on. Capture the trace id instead - `request_span` logs one per
  request - and fetch that id directly.
"""
from __future__ import annotations

import contextlib
import logging
import os

from app import config

logger = logging.getLogger(__name__)

# On by default now that it is verified. Flushing inside the request costs
# ~0.3s at the p50, because a 6-9s request gives the batch thread enough
# CPU to have exported already and the flush finds little left to do.
ENABLED = os.environ.get("ENABLE_TRACING", "true").lower() == "true"

_started = False


def start() -> bool:
    """Install the exporter. Returns whether tracing is actually on.

    Must be called before `app.orchestrator` is imported; see the module
    docstring on provider order.
    """
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


@contextlib.contextmanager
def request_span(name: str):
    """Wrap one HTTP request in a span and yield its trace id, or None.

    Without this each agent invocation starts its own root span, so a single
    /turn that scans and then explains lands in Cloud Trace as several
    unrelated traces. Grouping them under the request is the difference
    between "the model took 6s" and "this person waited 9s, and here is
    where it went".

    Yielding the trace id is what makes a log line and a trace joinable -
    and it is the only practical way to confirm export from Cloud Run,
    because the v1 traces.list API returns nothing while traces.get on a
    known id returns the spans. Diagnosing export by listing is how this
    was misread as broken the first time.
    """
    if not _started:
        yield None
        return

    from opentelemetry import trace

    tracer = trace.get_tracer("snapkaki")
    with tracer.start_as_current_span(name) as span:
        yield format(span.get_span_context().trace_id, "032x")


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
    if not _started:
        return
    from opentelemetry import trace

    # Ask for the provider that is actually installed rather than keeping
    # our own reference to the one we built. OpenTelemetry honours only the
    # first provider set in a process, so these are not always the same
    # object, and the installed one is the one holding the spans.
    force_flush = getattr(trace.get_tracer_provider(), "force_flush", None)
    if force_flush is None:
        # A no-op provider won the race; there is nothing buffered.
        return
    try:
        force_flush(timeout_ms)
    except Exception:
        logger.debug("span flush failed", exc_info=True)
