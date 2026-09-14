"""Version-bound SDK hooks; no provider requests, content or pricing inference."""
from contextvars import ContextVar
from functools import wraps
from importlib import metadata
from importlib.abc import Loader, MetaPathFinder
from importlib.machinery import PathFinder
import inspect
import os
import re
import sys
import threading

from ._vendor.guardian_exporter import BackgroundExporter
from ._vendor import guardian_openai as adapter

SUPPORTED = {"openai": "1.99.9", "litellm": "1.80.0"}
_DEPTH = ContextVar("sillage_capture_owner", default=0)
_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_LABEL = re.compile(r"[A-Za-z0-9_.:/-]{1,120}\Z")
_MODULES = {
    "litellm": "litellm",
    "openai.resources.responses.responses": "openai",
    "openai.resources.chat.completions.completions": "openai",
}


def detected_adapters():
    """Read installed distribution metadata without importing either SDK."""
    result = {}
    for package, supported in SUPPORTED.items():
        try:
            version = metadata.version(package)
        except Exception:
            version = None
        # Version text comes from third-party package metadata; cap diagnostics.
        safe_version = version if type(version) is str and re.fullmatch(r"[0-9A-Za-z.+_-]{1,50}", version) else None
        result[package] = {"installed": version is not None, "version": safe_version,
                           "supported": version == supported, "tested_version": supported}
    return result


def _safe(value, pattern, fallback=None):
    return value if type(value) is str and pattern.fullmatch(value) else fallback


class _AfterImport(Loader):
    def __init__(self, loader, owner):
        self.loader, self.owner = loader, owner

    def create_module(self, spec):
        create = getattr(self.loader, "create_module", None)
        return create(spec) if create else None

    def exec_module(self, module):
        self.loader.exec_module(module)
        self.owner._loaded(module)

    def __getattr__(self, name):
        return getattr(self.loader, name)


class _ImportHook(MetaPathFinder):
    def __init__(self, owner):
        self.owner = owner

    def find_spec(self, fullname, path=None, target=None):
        if fullname not in self.owner._modules:
            return None
        spec = PathFinder.find_spec(fullname, path, target)
        if spec and spec.loader and hasattr(spec.loader, "exec_module"):
            spec.loader = _AfterImport(spec.loader, self.owner)
        return spec


class _Terminal:
    def __init__(self, handle):
        self.handle, self.finished = handle, False

    def finish(self, status="unknown", usage=None):
        if not self.finished:
            self.finished = True
            adapter._finish(self.handle, status, usage)


def _observe_stream(stream, terminal, api, asynchronous):
    """Keep the SDK stream and context managers; wrap only its owned iterator."""
    if type(stream).__module__ != "openai" or type(stream).__name__ != ("AsyncStream" if asynchronous else "Stream"):
        terminal.finish()
        return stream
    iterator, original_close = stream._iterator, stream.close
    state = adapter._StreamState(api)
    if asynchronous:
        async def observed():
            try:
                while True:
                    try:
                        chunk = await anext(iterator)
                    except StopAsyncIteration:
                        terminal.finish(*state.result())
                        return
                    state.observe(chunk)
                    yield chunk
                    del chunk
            except BaseException as error:
                terminal.finish(adapter._error_status(error))
                raise

        async def close():
            # Closure can occur before the iterator was entered at all.
            terminal.finish()
            return await original_close()
    else:
        def observed():
            try:
                while True:
                    try:
                        chunk = next(iterator)
                    except StopIteration as completed:
                        terminal.finish(*state.result())
                        return completed.value
                    state.observe(chunk)
                    yield chunk
                    del chunk
            except BaseException as error:
                terminal.finish(adapter._error_status(error))
                raise

        def close():
            terminal.finish()
            return original_close()
    stream._iterator = observed()
    stream.close = close
    return stream


class Instrumentation:
    """Own one set of hooks and one lazy bounded exporter in this process.

    Install before application imports. Injection of a recording exporter is
    available for tests; it must implement the existing start_call/close contract.
    """
    def __init__(self, config, exporter=None, diagnostic=None):
        self.config, self._exporter = config, exporter
        self._diagnostic = diagnostic or (lambda _code: None)
        self._pid = os.getpid()
        self._lock = threading.Lock()
        self._patches, self._reported = [], set()
        self._hook, self._installed, self._closed = None, False, False
        self._modules = set()

    def _report(self, code):
        if code not in self._reported:
            self._reported.add(code)
            try:
                self._diagnostic(code)
            except BaseException:
                pass

    def _start(self, provider, args, kwargs):
        if self._closed or os.getpid() != self._pid:
            self._report("unsupported_child_process")
            return _Terminal(None)
        try:
            with self._lock:
                if self._exporter is None:
                    self._exporter = BackgroundExporter(origin=self.config.origin,
                        token=self.config.token, allow_local=self.config.allow_local)
            model = kwargs.get("model")
            if provider == "litellm" and model is None and args:
                model = args[0]
            fields = {"model": _safe(model, _LABEL, "unknown-model"),
                      "agent_name": self.config.service_name}
            if provider == "litellm":
                data = kwargs.get("metadata")
                if type(data) is dict:
                    fields["agent_name"] = _safe(dict.get(data, "generation_name"), _LABEL, self.config.service_name)
                    fields["trace_id"] = _safe(dict.get(data, "trace_id"), _ID)
            return _Terminal(self._exporter.start_call(**fields))
        except BaseException:
            self._report("capture_unavailable")
            return _Terminal(None)

    def _wrap(self, original, provider, api, asynchronous):
        positional_stream = None
        if provider == "litellm":
            try:
                names = [name for name, parameter in inspect.signature(original).parameters.items()
                         if parameter.kind in (parameter.POSITIONAL_ONLY, parameter.POSITIONAL_OR_KEYWORD)]
                positional_stream = names.index("stream") if "stream" in names else None
            except Exception:
                pass

        def streaming(args, kwargs):
            if "stream" in kwargs:
                return kwargs["stream"] is True
            return positional_stream is not None and len(args) > positional_stream and args[positional_stream] is True

        def skip(kwargs, streamed):
            if provider == "litellm" and streamed:
                self._report("litellm_streaming_not_supported")
                return True
            # SDK raw-response helpers use a private header to request another
            # return interface. Preserve it; this adapter does not parse raw HTTP.
            headers = kwargs.get("extra_headers")
            if type(headers) is dict and any(type(key) is str and key.lower() == "x-stainless-raw-response" for key in headers):
                self._report("openai_raw_response_not_supported")
                return True
            return False

        def result(value, terminal, streamed):
            try:
                if streamed and provider == "openai":
                    return _observe_stream(value, terminal, api, asynchronous)
                terminal.finish(*adapter._completion(value, api))
            except BaseException:
                terminal.finish()
                self._report("capture_unavailable")
            return value

        if asynchronous:
            @wraps(original)
            async def wrapped(*args, **kwargs):
                if _DEPTH.get() or self._closed:
                    return await original(*args, **kwargs)
                streamed = streaming(args, kwargs)
                bypass = skip(kwargs, streamed)
                terminal = None if bypass else self._start(provider, args, kwargs)
                marker = _DEPTH.set(_DEPTH.get() + 1)
                try:
                    value = await original(*args, **kwargs)
                except BaseException as error:
                    if terminal:
                        terminal.finish(adapter._error_status(error))
                    raise
                finally:
                    _DEPTH.reset(marker)
                return value if bypass else result(value, terminal, streamed)
        else:
            @wraps(original)
            def wrapped(*args, **kwargs):
                if _DEPTH.get() or self._closed:
                    return original(*args, **kwargs)
                streamed = streaming(args, kwargs)
                bypass = skip(kwargs, streamed)
                terminal = None if bypass else self._start(provider, args, kwargs)
                marker = _DEPTH.set(_DEPTH.get() + 1)
                try:
                    value = original(*args, **kwargs)
                except BaseException as error:
                    if terminal:
                        terminal.finish(adapter._error_status(error))
                    raise
                finally:
                    _DEPTH.reset(marker)
                return value if bypass else result(value, terminal, streamed)
        wrapped.__sillage_owner__ = self
        return wrapped

    def _patch(self, value, name, provider, api, asynchronous):
        original = getattr(value, name, None)
        if not callable(original):
            self._report("adapter_surface_unavailable")
            return
        if getattr(original, "__sillage_owner__", None) is not None:
            if original.__sillage_owner__ is not self:
                self._report("adapter_already_instrumented")
            return
        wrapped = self._wrap(original, provider, api, asynchronous)
        setattr(value, name, wrapped)
        self._patches.append((value, name, original, wrapped))

    def _loaded(self, module):
        try:
            if module.__name__ == "litellm":
                for name, asynchronous in (("completion", False), ("acompletion", True)):
                    self._patch(module, name, "litellm", "chat_completions", asynchronous)
            else:
                responses = module.__name__.endswith("responses.responses")
                base, api = ("Responses", "responses") if responses else ("Completions", "chat_completions")
                for prefix, asynchronous in (("", False), ("Async", True)):
                    value = getattr(module, prefix + base)
                    for method in ("create", "parse"):
                        self._patch(value, method, "openai", api, asynchronous)
        except BaseException:
            self._report("adapter_install_failed")

    def install(self):
        if self._closed:
            raise RuntimeError("instrumentation_closed")
        if self._installed:
            return self
        versions = detected_adapters()
        self._modules = {name for name, package in _MODULES.items() if versions[package]["supported"]}
        for package, info in versions.items():
            if info["installed"] and not info["supported"]:
                self._report(package + "_version_not_supported")
        self._hook = _ImportHook(self)
        # Preserve pre-existing non-filesystem importers; support ordinary wheels.
        index = next((i for i, finder in enumerate(sys.meta_path) if finder is PathFinder), len(sys.meta_path))
        sys.meta_path.insert(index, self._hook)
        self._installed = True
        for name in self._modules:
            module = sys.modules.get(name)
            if module is not None:
                self._loaded(module)
        return self

    def close(self, timeout=3):
        if self._closed:
            return None
        self._closed = True
        if self._hook in sys.meta_path:
            sys.meta_path.remove(self._hook)
        for value, name, original, wrapped in reversed(self._patches):
            if getattr(value, name, None) is wrapped:
                setattr(value, name, original)
        self._patches.clear()
        if self._exporter is not None and os.getpid() == self._pid:
            try:
                return self._exporter.close(timeout=timeout)
            except BaseException:
                self._report("export_shutdown_unconfirmed")
        return None
