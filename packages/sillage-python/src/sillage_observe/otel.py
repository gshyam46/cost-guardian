"""Project recognised ended LLM spans into Sillage's numeric event contract.

This processor never serializes spans, events, resources, baggage or arbitrary
attributes. The application's provider, sampling and other processors stay owned
by the application. Install the optional OpenTelemetry dependencies to import it.
"""
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
import math
import os
import re
import threading
import time

from opentelemetry import context as otel_context
from opentelemetry.sdk.trace import SpanProcessor
from opentelemetry.trace import StatusCode

from ._vendor.guardian_exporter import BackgroundExporter

AGENT_CONTEXT_KEY = "sillage.agent.name"
_MISSING = object()
_LABEL = re.compile(r"[A-Za-z0-9_.:/-]{1,120}\Z")
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_MAX_TOKENS = 2**53 - 1
_CONTEXT_LIMIT = 2048
_CONTEXT_TTL = 300.0
_INPUT = ("llm.token_count.prompt", "gen_ai.usage.input_tokens", "gen_ai.usage.prompt_tokens")
_OUTPUT = ("llm.token_count.completion", "gen_ai.usage.output_tokens", "gen_ai.usage.completion_tokens")
_TOTAL = ("llm.token_count.total", "gen_ai.usage.total_tokens")
_MODEL = ("gen_ai.response.model", "llm.model_name", "gen_ai.request.model")
_AGENT = ("sillage.agent.name", "gen_ai.agent.name")
_OPERATION = {"chat", "text_completion"}
_INTERRUPTED = {"unknown", "incomplete", "cancelled", "canceled", "interrupted", "in_progress", "queued"}
_TRUNCATED = {"length", "content_filter", "max_tokens", "max_output_tokens", "incomplete", "cancelled", "canceled"}
_TERMINAL = {"stop", "tool_calls", "function_call", "end_turn", "stop_sequence"}
_PROVIDER_SCOPES = {"openinference.instrumentation.openai", "openinference.instrumentation.litellm"}
_PROVIDER_LLM_NAMES = {
    "openinference.instrumentation.openai": {"ChatCompletion", "Completion", "Response"},
    "openinference.instrumentation.litellm": {"completion", "acompletion", "completion_with_retries", "responses", "aresponses"},
}
_DIAGNOSTICS = frozenset({
    "unsupported_span", "invalid_span", "invalid_token_measurements", "context_evicted",
    "nested_llm_spans_observed", "capture_unavailable", "export_rejected", "queue_full",
    "credential_rejected", "exporter_unavailable", "invalid_event", "closed",
    "flush_unconfirmed", "shutdown_unconfirmed", "unsupported_child_process",
    "missing_terminal_evidence",
})


def _attribute(attributes, key):
    # Explicit single-key reads only: never iterate, copy or serialize attributes.
    return attributes.get(key, _MISSING) if attributes is not None else _MISSING


def _label(value):
    return value if type(value) is str and _LABEL.fullmatch(value) else None


def _first_label(attributes, keys):
    for key in keys:
        value = _label(_attribute(attributes, key))
        if value is not None:
            return value
    return None


def _ids(span):
    context = span.get_span_context()
    trace, identifier = context.trace_id, context.span_id
    if type(trace) is not int or not 0 < trace < 2**128 or type(identifier) is not int or not 0 < identifier < 2**64:
        raise ValueError()
    parent = span.parent
    parent_id = None
    if parent is not None:
        if type(parent.trace_id) is not int or parent.trace_id != trace:
            raise ValueError()
        parent_id = parent.span_id
        if type(parent_id) is not int or not 0 < parent_id < 2**64 or parent_id == identifier:
            raise ValueError()
    return trace, identifier, parent_id


def _provider_function_supported(span):
    if span is None:
        return True
    scope = span.instrumentation_scope
    scope_name = scope.name if scope is not None else None
    if type(scope_name) is str and scope_name in _PROVIDER_LLM_NAMES:
        # Known instrumentors also label image/audio API results LLM.
        # Read only this technical function name; never export it.
        name = span.name
        return type(name) is str and name in _PROVIDER_LLM_NAMES[scope_name]
    return True


def _kind(attributes, span=None):
    kind = _attribute(attributes, "openinference.span.kind")
    operation = _attribute(attributes, "gen_ai.operation.name")
    if kind is not _MISSING:
        if type(kind) is not str:
            return None
        if kind == "LLM":
            # An explicit incompatible operation cannot be repaired by a name.
            if operation is not _MISSING and (type(operation) is not str or operation not in _OPERATION):
                return None
            return "LLM" if _provider_function_supported(span) else None
        return "AGENT" if kind == "AGENT" else None
    if type(operation) is str and operation in _OPERATION and _first_label(attributes, _MODEL):
        return "LLM" if _provider_function_supported(span) else None
    return None


def _counter_aliases(attributes, keys):
    values = []
    for key in keys:
        value = _attribute(attributes, key)
        if value is _MISSING or value is None:
            continue
        if type(value) is not int or not 0 <= value <= _MAX_TOKENS:
            raise ValueError()
        values.append(value)
    if values and any(value != values[0] for value in values[1:]):
        raise ValueError()
    return values[0] if values else None


def _tokens(attributes):
    inp, out, total = (_counter_aliases(attributes, keys) for keys in (_INPUT, _OUTPUT, _TOTAL))
    if inp is not None and out is not None:
        summed = inp + out
        if summed > _MAX_TOKENS or total is not None and total != summed:
            raise ValueError()
        total = summed
    if total is not None and any(value is not None and value > total for value in (inp, out)):
        raise ValueError()
    return {"input_tokens": inp, "output_tokens": out, "total_tokens": total}


def _outcome(span, attributes, missing_terminal=None):
    completed = False
    for key in ("sillage.call.status", "gen_ai.response.status"):
        value = _attribute(attributes, key)
        if type(value) is str and value in _INTERRUPTED:
            return "unknown"
        completed = completed or type(value) is str and value in {"success", "completed"}
    reasons = []
    for key in ("gen_ai.response.finish_reason", "llm.finish_reason"):
        value = _attribute(attributes, key)
        if value is not _MISSING and value is not None:
            if type(value) is not str or len(value) > 64:
                return "unknown"
            reasons.append(value)
    plural = _attribute(attributes, "gen_ai.response.finish_reasons")
    if plural is not _MISSING and plural is not None:
        # The sole sequence exception is a bounded list of terminal codes, never
        # content-bearing arrays, events or arbitrary nested attributes.
        if type(plural) not in (tuple, list) or len(plural) > 8:
            return "unknown"
        for value in plural:
            if type(value) is not str or len(value) > 64:
                return "unknown"
            reasons.append(value)
    if any(value in _TRUNCATED for value in reasons):
        return "unknown"
    if reasons and any(value not in _TERMINAL for value in reasons):
        return "unknown"
    completed = completed or bool(reasons) and all(value in _TERMINAL for value in reasons)
    # Never read status.description or exception events. UNSET is not success.
    code = span.status.status_code
    if code is StatusCode.ERROR:
        return "error"
    if code is StatusCode.OK:
        scope = span.instrumentation_scope
        scope_name = scope.name if scope is not None else None
        if type(scope_name) is str and scope_name in _PROVIDER_SCOPES and not completed:
            # These provider instrumentors can end an interrupted stream with OK.
            # Never inspect request JSON to guess whether streaming was enabled.
            if missing_terminal is not None:
                missing_terminal()
            return "unknown"
        return "success"
    return "unknown"


def _timestamps(span):
    start, end = span.start_time, span.end_time
    if type(start) is not int or type(end) is not int or not 0 < start <= end < 2**63:
        raise ValueError()
    def stamp(nanos):
        return (_EPOCH + timedelta(milliseconds=nanos // 1_000_000)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return stamp(start), stamp(end)


class SillageSpanProcessor(SpanProcessor):
    """Bounded projection with scalar agent context and an optional test sink."""
    def __init__(self, config, exporter=None, diagnostic=None):
        self.config, self._exporter = config, exporter
        self._diagnostic = diagnostic or (lambda _code: None)
        self._pid, self._closed = os.getpid(), False
        self._lock = threading.RLock()
        self._contexts = OrderedDict()
        self._reported = set()
        self._accepted = self._rejected = self._ignored = 0
        self._evicted = self._nested = 0
        self._missing_terminal = 0
        self._last_diagnostic = None
        self._close_result = None

    def _report(self, code):
        code = code if code in _DIAGNOSTICS else "export_rejected"
        self._last_diagnostic = code
        if code in self._reported:
            return
        self._reported.add(code)
        try:
            self._diagnostic(code)
        except BaseException:
            pass

    def _live(self):
        if os.getpid() != self._pid:
            # Never enter an inherited lock. A launcher must initialise separately
            # in a child process; this processor does not export parent buffers.
            self._report("unsupported_child_process")
            return False
        return not self._closed

    def _expire(self, now):
        while self._contexts:
            key, value = next(iter(self._contexts.items()))
            if value[3] > now:
                break
            self._contexts.pop(key)
            self._evicted += 1
        while len(self._contexts) > _CONTEXT_LIMIT:
            self._contexts.popitem(last=False)
            self._evicted += 1
        if self._evicted:
            self._report("context_evicted")

    def _remember(self, key, parent, agent, kind, now):
        self._contexts.pop(key, None)
        # Every entry is only: agent label, parent integer, LLM bool and deadline.
        self._contexts[key] = (agent, parent, kind == "LLM", now + _CONTEXT_TTL)
        self._expire(now)

    def _parent_context(self, trace, parent):
        agent, nested, seen = None, False, set()
        while parent is not None and parent not in seen and len(seen) < 64:
            seen.add(parent)
            value = self._contexts.get((trace, parent))
            if value is None:
                break
            if agent is None:
                agent = value[0]
            nested = nested or value[2]
            parent = value[1]
        return agent, nested

    def _missing_finish(self):
        self._missing_terminal += 1
        self._report("missing_terminal_evidence")

    def on_start(self, span, parent_context=None):
        if not self._live():
            return
        try:
            trace, identifier, parent = _ids(span)
            attributes = span.attributes
            kind = _kind(attributes, span)
            explicit = _first_label(attributes, _AGENT)
            contextual = _label(otel_context.get_value(AGENT_CONTEXT_KEY, parent_context))
            with self._lock:
                if self._closed:
                    return
                now = time.monotonic()
                self._expire(now)
                inherited, _nested = self._parent_context(trace, parent)
                agent = explicit or contextual or (_label(span.name) if kind == "AGENT" else None) or inherited
                self._remember((trace, identifier), parent, agent, kind, now)
        except BaseException:
            self._report("invalid_span")

    def on_end(self, span):
        if not self._live():
            return
        try:
            trace, identifier, parent = _ids(span)
            attributes = span.attributes
            kind = _kind(attributes, span)
            explicit = _first_label(attributes, _AGENT)
            with self._lock:
                if self._closed:
                    return
                now = time.monotonic()
                self._expire(now)
                remembered = self._contexts.get((trace, identifier))
                inherited, nested = self._parent_context(trace, parent)
                agent = explicit or (remembered[0] if remembered else None) or (_label(span.name) if kind == "AGENT" else None) or inherited
                self._remember((trace, identifier), parent, agent, kind, now)
                if kind != "LLM":
                    self._ignored += 1
                    self._report("unsupported_span")
                    return
                if nested:
                    self._nested += 1
                    self._report("nested_llm_spans_observed")
                started, ended = _timestamps(span)
                try:
                    usage = _tokens(attributes)
                except (ValueError, TypeError):
                    usage = {"input_tokens": None, "output_tokens": None, "total_tokens": None}
                    self._report("invalid_token_measurements")
                event = {"observation_id": f"{identifier:016x}", "trace_id": f"{trace:032x}",
                         "agent_name": agent or _label(self.config.service_name) or "python-app",
                         "model": _first_label(attributes, _MODEL) or "unknown-model",
                         "started_at": started, "ended_at": ended,
                         "status": _outcome(span, attributes, self._missing_finish), "cost_usd": None, **usage}
                if parent is not None:
                    event["parent_observation_id"] = f"{parent:016x}"
                if self._exporter is None:
                    self._exporter = BackgroundExporter(origin=self.config.origin, token=self.config.token,
                                                        allow_local=self.config.allow_local)
                result = self._exporter.emit(event)
                if type(result) is dict and result.get("accepted") is True:
                    self._accepted += 1
                else:
                    self._rejected += 1
                    code = result.get("code") if type(result) is dict else None
                    self._report(code if type(code) is str else "export_rejected")
        except BaseException:
            with self._lock:
                self._rejected += 1
            self._report("capture_unavailable")

    def snapshot(self):
        if os.getpid() != self._pid:
            return {"closed": True, "accepted_spans": 0, "rejected_spans": 0, "ignored_spans": 0,
                    "context_entries": 0, "evicted_contexts": 0, "nested_llm_spans": 0,
                    "missing_terminal_evidence_spans": 0,
                    "last_diagnostic": "unsupported_child_process"}
        with self._lock:
            self._expire(time.monotonic())
            return {"closed": self._closed, "accepted_spans": self._accepted, "rejected_spans": self._rejected,
                    "ignored_spans": self._ignored, "context_entries": len(self._contexts),
                    "evicted_contexts": self._evicted, "nested_llm_spans": self._nested,
                    "missing_terminal_evidence_spans": self._missing_terminal,
                    "last_diagnostic": self._last_diagnostic}

    def force_flush(self, timeout_millis=30000):
        if not self._live():
            return False
        if type(timeout_millis) not in (int, float) or not math.isfinite(timeout_millis) or not 0 <= timeout_millis <= 300000:
            return False
        try:
            with self._lock:
                exporter = self._exporter
            if exporter is None:
                return True
            result = exporter.flush(timeout=timeout_millis / 1000)
            confirmed = type(result) is dict and result.get("confirmed") is True
            if not confirmed:
                self._report("flush_unconfirmed")
            return confirmed
        except BaseException:
            self._report("flush_unconfirmed")
            return False

    def close(self, timeout=3):
        if os.getpid() != self._pid:
            return {"drained": False, "confirmed": False, "stats": self.snapshot()}
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 <= timeout <= 300:
            timeout = 0
        with self._lock:
            if self._closed:
                return self._close_result or {"drained": False, "confirmed": False, "stats": self.snapshot()}
            self._closed = True
            self._contexts.clear()
            exporter = self._exporter
        confirmed, drained = exporter is None, exporter is None
        try:
            if exporter is not None:
                result = exporter.close(timeout=timeout)
                confirmed = type(result) is dict and result.get("confirmed") is True
                drained = type(result) is dict and result.get("drained") is True
        except BaseException:
            pass
        if not confirmed:
            self._report("shutdown_unconfirmed")
        with self._lock:
            self._close_result = {"drained": drained, "confirmed": confirmed, "stats": self.snapshot()}
            return self._close_result

    def shutdown(self):
        self.close(timeout=3)
