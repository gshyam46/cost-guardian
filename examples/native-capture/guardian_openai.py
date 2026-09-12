"""Content-free OpenAI usage adapters for an application-owned SDK operation.

No SDK import, client construction, credentials, content serialization or pricing.
Only scalar usage and lifecycle metadata survive inspection of a provider object.
"""
import asyncio
import inspect
import re
from types import GetSetDescriptorType, MemberDescriptorType

_MAX = 2**53 - 1
_MISSING = object()
_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_APIS = ("responses", "chat_completions")
_RESPONSE_TERMINAL = {"completed": "success", "failed": "error", "incomplete": "unknown"}
_CHAT_TERMINAL = {"stop": "success", "tool_calls": "success", "function_call": "success",
                  "length": "unknown", "content_filter": "unknown"}


def _unknown():
    return {"input_tokens": None, "output_tokens": None, "total_tokens": None}


def _stored(value, attribute="__dict__"):
    if type(value) is dict:
        return value
    # Read real Pydantic model storage via its builtin __dict__ descriptor. This
    # bypasses instance getters and never calls model_dump/dict/custom serializers.
    cls = type(value)
    bases = type.__getattribute__(cls, "__mro__")
    if not any(type.__getattribute__(base, "__module__") in ("pydantic.main", "pydantic.v1.main")
               and type.__getattribute__(base, "__name__") == "BaseModel" for base in bases):
        raise ValueError()
    for base in bases:
        descriptor = type.__getattribute__(base, "__dict__").get(attribute)
        if type(descriptor) in (GetSetDescriptorType, MemberDescriptorType):
            stored = descriptor.__get__(value, cls)
            if type(stored) is dict:
                return stored
            if attribute == "__pydantic_extra__" and stored is None:
                return {}
            raise ValueError()
    if attribute == "__pydantic_extra__":
        # Pydantic v1 stores extras in __dict__, without a separate slot.
        return {}
    raise ValueError()


def _get(value, name, default=_MISSING):
    stored = _stored(value)
    if name in stored:
        return dict.get(stored, name)
    if type(value) is not dict:
        # New provider fields may live in v2's extra storage. Inspect only the
        # requested allowlisted key through its builtin descriptor, never model
        # getters, serializers or the remaining provider payload.
        return dict.get(_stored(value, "__pydantic_extra__"), name, default)
    return default


def _counter(value):
    if value is _MISSING or value is None:
        return None
    if type(value) is not int or not 0 <= value <= _MAX:
        raise ValueError()
    return value


def _usage(response, api):
    if type(api) is not str or api not in _APIS:
        raise ValueError()
    usage = _get(response, "usage")
    if usage is _MISSING or usage is None:
        return _unknown()
    inputs, outputs = ("input_tokens", "output_tokens") if api == "responses" else ("prompt_tokens", "completion_tokens")
    inp, out, total = (_counter(_get(usage, name)) for name in (inputs, outputs, "total_tokens"))
    if inp is not None and out is not None:
        summed = _counter(inp + out)
        if total is not None and total != summed:
            raise ValueError()
        total = summed
    if total is not None and any(number is not None and number > total for number in (inp, out)):
        raise ValueError()
    details = (("input_tokens_details", ("cached_tokens", "cache_write_tokens"), inp), ("output_tokens_details", ("reasoning_tokens",), out)) if api == "responses" else (
        ("prompt_tokens_details", ("cached_tokens", "cache_write_tokens"), inp), ("completion_tokens_details", ("reasoning_tokens",), out))
    for field, children, parent in details:
        container = _get(usage, field)
        if container is _MISSING or container is None:
            continue
        for child in children:
            subset = _counter(_get(container, child))
            if subset is not None and any(limit is not None and subset > limit for limit in (parent, total)):
                raise ValueError()
    return {"input_tokens": inp, "output_tokens": out, "total_tokens": total}


def extract_openai_usage(response, api="responses"):
    """Return only validated numeric usage; malformed snapshots become unknown."""
    try:
        return _usage(response, api)
    except BaseException:
        return _unknown()


def _chat_reason(response):
    choices = _get(response, "choices")
    if type(choices) is not list or len(choices) != 1:
        return None
    choice = choices[0]
    index, reason = _get(choice, "index"), _get(choice, "finish_reason")
    if type(index) is not int or index != 0 or type(reason) is not str or reason not in _CHAT_TERMINAL:
        return None
    return reason


def _completion(response, api):
    if type(api) is not str or api not in _APIS:
        return "unknown", _unknown()
    expected = "response" if api == "responses" else "chat.completion"
    kind = _get(response, "object")
    if type(kind) is not str or kind != expected:
        return "unknown", _unknown()
    if api == "responses":
        terminal = _get(response, "status")
        if type(terminal) is str and terminal in _RESPONSE_TERMINAL:
            return _RESPONSE_TERMINAL[terminal], extract_openai_usage(response, api)
    elif api == "chat_completions":
        reason = _chat_reason(response)
        if reason is not None:
            return _CHAT_TERMINAL[reason], extract_openai_usage(response, api)
    return "unknown", _unknown()


def _start(exporter, metadata):
    try:
        return exporter.start_call(**metadata)
    except BaseException:
        return None


def _finish(handle, status, usage=None):
    try:
        if handle is not None:
            handle.finish(status, **(usage or _unknown()))
    except BaseException:
        pass


def _result(handle, response, api):
    try:
        status, usage = _completion(response, api)
    except BaseException:
        status, usage = "unknown", _unknown()
    _finish(handle, status, usage)


def _error_status(error):
    return "error" if isinstance(error, Exception) else "unknown"


def openai_call(exporter, operation, *, api="responses", agent_name, model, trace_id=None, parent_observation_id=None):
    handle = _start(exporter, dict(agent_name=agent_name, model=model, trace_id=trace_id,
                                  parent_observation_id=parent_observation_id))
    try:
        result = operation()
    except BaseException as error:
        _finish(handle, _error_status(error))
        raise
    _result(handle, result, api)
    return result


async def async_openai_call(exporter, operation, *, api="responses", agent_name, model, trace_id=None, parent_observation_id=None):
    handle = _start(exporter, dict(agent_name=agent_name, model=model, trace_id=trace_id,
                                  parent_observation_id=parent_observation_id))
    try:
        result = operation()
        if inspect.isawaitable(result):
            result = await result
    except BaseException as error:
        _finish(handle, _error_status(error))
        raise
    _result(handle, result, api)
    return result


class _StreamState:
    """One bounded ID, marker and numeric tuple; never retain provider chunks."""
    def __init__(self, api):
        self.api = api
        self.identifier = self.terminal = self.usage = None
        self.valid_usage = None
        self.bad_usage = self.error = False
        self.conflict = type(api) is not str or api not in _APIS

    def _bind(self, value):
        if type(value) is not str or not _ID.fullmatch(value):
            self.conflict = True
        elif self.identifier is None:
            self.identifier = value
        elif self.identifier != value:
            self.conflict = True

    def _terminal(self, marker):
        if self.terminal is not None and self.terminal != marker:
            self.conflict = True
        self.terminal = marker

    def _usage(self, response):
        try:
            usage = tuple(_usage(response, self.api).values())
        except BaseException:
            self.bad_usage = True
            self.usage = (None, None, None)
            return
        if self.valid_usage is not None and self.valid_usage != usage:
            self.conflict = True
        self.valid_usage = usage
        if not self.bad_usage:
            self.usage = usage

    def observe(self, chunk):
        try:
            self._observe(chunk)
        except BaseException:
            self.conflict = True

    def _observe(self, chunk):
        if self.conflict:
            return
        if self.api == "responses":
            event_type = _get(chunk, "type")
            if type(event_type) is not str:
                return
            if event_type == "error":
                self.error = True
                return
            if event_type not in (
                    "response.created", "response.in_progress",
                    "response.completed", "response.failed", "response.incomplete"):
                return
            response = _get(chunk, "response")
            self._bind(_get(response, "id"))
            terminal = event_type.removeprefix("response.")
            if terminal in _RESPONSE_TERMINAL:
                status, kind = _get(response, "status"), _get(response, "object")
                if type(status) is not str or status != terminal or type(kind) is not str or kind != "response":
                    self.conflict = True
                self._terminal(terminal)
                self._usage(response)
        else:
            kind = _get(chunk, "object")
            if type(kind) is not str or kind != "chat.completion.chunk":
                self.conflict = True
                return
            self._bind(_get(chunk, "id"))
            choices = _get(chunk, "choices")
            if type(choices) is not list or len(choices) > 1:
                self.conflict = True
                return
            usage = _get(chunk, "usage")
            if not choices:
                if usage is not _MISSING and usage is not None:
                    if self.terminal is None:
                        self.conflict = True
                    self._usage(chunk)
                return
            # Usage on choice/delta chunks is not a final completion snapshot.
            choice = choices[0]
            if type(_get(choice, "index")) is not int or _get(choice, "index") != 0:
                self.conflict = True
                return
            reason = _get(choice, "finish_reason")
            if reason is not _MISSING and reason is not None:
                if type(reason) is not str or reason not in _CHAT_TERMINAL:
                    self.conflict = True
                else:
                    self._terminal(reason)

    def result(self):
        if self.conflict or self.error and self.terminal not in (None, "failed"):
            return "unknown", _unknown()
        if self.error:
            return "error", dict(zip(("input_tokens", "output_tokens", "total_tokens"), self.usage or (None, None, None)))
        if self.terminal is None:
            return "unknown", _unknown()
        if self.api == "responses":
            status = _RESPONSE_TERMINAL.get(self.terminal, "unknown")
        else:
            status = _CHAT_TERMINAL.get(self.terminal, "unknown")
        return status, dict(zip(("input_tokens", "output_tokens", "total_tokens"), self.usage or (None, None, None)))


def _close(stream, iterator):
    for value in (iterator, stream if stream is not iterator else None):
        try:
            if value is not None:
                closer = getattr(value, "close", None)
                if closer is not None:
                    closer()
        except BaseException:
            pass


async def _aclose(stream, iterator):
    for value in (iterator, stream if stream is not iterator else None):
        try:
            if value is not None:
                closer = getattr(value, "aclose", None) or getattr(value, "close", None)
                if closer is not None:
                    result = closer()
                    if inspect.isawaitable(result):
                        await result
        except BaseException:
            pass


def openai_stream(exporter, operation, *, api="responses", agent_name, model, trace_id=None, parent_observation_id=None):
    handle = _start(exporter, dict(agent_name=agent_name, model=model, trace_id=trace_id,
                                  parent_observation_id=parent_observation_id))
    state, stream, iterator = _StreamState(api), None, None
    status, usage = "unknown", _unknown()
    yielding = False
    try:
        stream = operation()
        iterator = iter(stream)
        while True:
            try:
                chunk = next(iterator)
            except StopIteration as completed:
                status, usage = state.result()
                return completed.value
            state.observe(chunk)
            yielding = True
            yield chunk
            yielding = False
            del chunk
    except BaseException as error:
        status, usage = "unknown" if yielding else _error_status(error), _unknown()
        raise
    finally:
        _finish(handle, status, usage)
        _close(stream, iterator)


async def async_openai_stream(exporter, operation, *, api="responses", agent_name, model, trace_id=None, parent_observation_id=None):
    handle = _start(exporter, dict(agent_name=agent_name, model=model, trace_id=trace_id,
                                  parent_observation_id=parent_observation_id))
    state, stream, iterator = _StreamState(api), None, None
    status, usage = "unknown", _unknown()
    yielding = False
    try:
        stream = operation()
        if inspect.isawaitable(stream):
            stream = await stream
        iterator = aiter(stream)
        while True:
            try:
                chunk = await anext(iterator)
            except StopAsyncIteration:
                status, usage = state.result()
                return
            state.observe(chunk)
            yielding = True
            yield chunk
            yielding = False
            del chunk
    except BaseException as error:
        status, usage = "unknown" if yielding else _error_status(error), _unknown()
        raise
    finally:
        _finish(handle, status, usage)
        await _aclose(stream, iterator)
