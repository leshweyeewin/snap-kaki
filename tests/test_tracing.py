"""Does flush() actually flush?

This exists because of a bug that hid for days. `start()` declared only
`global _started`, so its `_provider = provider` bound a local, the
module-level `_provider` stayed None, and `flush()` returned early on
every single call. No exception, no log line, no spans - and the
conclusion drawn from the silence was that Cloud Trace export did not
work, which went into the docs as fact.

Nothing about that was observable from outside, which is the point of
these tests: they assert spans actually leave, not that a function was
reached.
"""
import os

os.environ.setdefault("USE_STUB", "true")

import pytest

from app import tracing


@pytest.fixture
def in_memory_provider():
    """A real TracerProvider with a real BatchSpanProcessor, exporting to
    memory instead of Cloud Trace.

    Batched on purpose: an in-memory exporter with a SimpleSpanProcessor
    would export on span end and pass whether or not flush did anything,
    which is exactly the bug this is here to catch.
    """
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(
        # Long delay so the background thread cannot rescue us; only an
        # explicit flush can get these spans out inside the test.
        BatchSpanProcessor(exporter, schedule_delay_millis=600_000)
    )
    # OpenTelemetry honours only the first provider set in a process and
    # refuses to replace it, so override the private slot directly. That is
    # the same constraint the module docstring describes.
    trace._TRACER_PROVIDER = provider
    yield provider, exporter
    trace._TRACER_PROVIDER = None


def test_flush_exports_buffered_spans(in_memory_provider, monkeypatch):
    provider, exporter = in_memory_provider
    monkeypatch.setattr(tracing, "_started", True)

    from opentelemetry import trace

    with trace.get_tracer("test").start_as_current_span("a_span"):
        pass

    assert exporter.get_finished_spans() == (), "batched: nothing should have left yet"

    tracing.flush(5000)

    names = [s.name for s in exporter.get_finished_spans()]
    assert names == ["a_span"], f"flush did not export anything: {names}"


def test_flush_is_a_no_op_when_tracing_never_started(in_memory_provider, monkeypatch):
    """The off-by-default path must not flush someone else's provider."""
    _provider, exporter = in_memory_provider
    monkeypatch.setattr(tracing, "_started", False)

    from opentelemetry import trace

    with trace.get_tracer("test").start_as_current_span("a_span"):
        pass

    tracing.flush(5000)
    assert exporter.get_finished_spans() == ()


def test_flush_survives_a_provider_that_cannot_flush(monkeypatch):
    """Before ours is installed, the global provider is a no-op proxy with
    no force_flush. Asking it to flush must not raise into a request."""
    from opentelemetry import trace

    monkeypatch.setattr(tracing, "_started", True)
    monkeypatch.setattr(trace, "get_tracer_provider", lambda: object())
    tracing.flush(100)  # must not raise


def test_start_does_nothing_in_stub_mode():
    """Offline demo runs have no project and must not try to export."""
    from app import config

    assert config.USE_STUB
    assert tracing.start() is False
    assert tracing.active() is False


def test_request_span_groups_children_and_yields_its_trace_id(
    in_memory_provider, monkeypatch
):
    """One HTTP request must produce ONE trace, not one per agent call."""
    provider, exporter = in_memory_provider
    monkeypatch.setattr(tracing, "_started", True)

    from opentelemetry import trace

    tracer = trace.get_tracer("test")
    with tracing.request_span("POST /turn") as trace_id:
        assert trace_id and len(trace_id) == 32
        # Stand-ins for the agent spans ADK creates inside a request.
        with tracer.start_as_current_span("invoke_agent vision"):
            pass
        with tracer.start_as_current_span("invoke_agent field_explainer"):
            pass

    tracing.flush(5000)
    spans = exporter.get_finished_spans()
    assert {s.name for s in spans} == {
        "POST /turn", "invoke_agent vision", "invoke_agent field_explainer",
    }
    # The point of the wrapper: all three share one trace id, so Cloud Trace
    # shows the request the user waited on rather than three fragments.
    ids = {format(s.context.trace_id, "032x") for s in spans}
    assert ids == {trace_id}, ids


def test_request_span_yields_none_when_tracing_is_off(monkeypatch):
    """The caller uses the yielded id to decide whether to log it."""
    monkeypatch.setattr(tracing, "_started", False)
    with tracing.request_span("POST /turn") as trace_id:
        assert trace_id is None
