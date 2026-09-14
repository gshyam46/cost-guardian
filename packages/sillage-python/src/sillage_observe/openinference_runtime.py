"""Opt-in upstream instrumentation. Import/check use distribution metadata only."""
from functools import wraps
from importlib import import_module, metadata
import hashlib
import inspect
import os
import re
import sys
import threading

from .configuration import ConfigurationError

SHARED_VERSIONS = {
    "opentelemetry-sdk": "1.37.0",
    "opentelemetry-api": "1.37.0",
    "opentelemetry-instrumentation": "0.58b0",
    "openinference-instrumentation": "0.1.60",
    "openinference-semantic-conventions": "0.1.37",
}
LAYERS = {
    "langchain": ("langchain-core", ("1.2.5",), "0.1.74", "LangChainInstrumentor"),
    "litellm": ("litellm", ("1.80.0",), "0.1.34", "LiteLLMInstrumentor"),
    "openai": ("openai", ("1.99.9", "2.54.0"), "0.1.58", "OpenAIInstrumentor"),
}
_LABEL = re.compile(r"[A-Za-z0-9_.:/-]{1,120}\Z")
_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_ACTIVE = None
_LOCK = threading.Lock()


def _version(name):
    try:
        value = metadata.version(name)
    except Exception:
        return None
    return value if type(value) is str and re.fullmatch(r"[0-9A-Za-z.+_-]{1,50}", value) else None


def detected_openinference():
    """No SDK import, environment scan, threads or network access."""
    shared = {name: {"version": _version(name), "tested_version": expected}
              for name, expected in SHARED_VERSIONS.items()}
    dependencies_ready = all(item["version"] == item["tested_version"] for item in shared.values())
    adapters = {}
    for name, (sdk, tested, upstream, _class_name) in LAYERS.items():
        sdk_version = _version(sdk)
        instrumentor_version = _version("openinference-instrumentation-" + name)
        adapters[name] = {"installed": sdk_version is not None, "version": sdk_version,
            "tested_versions": list(tested), "instrumentor_version": instrumentor_version,
            "tested_instrumentor_version": upstream,
            "supported": dependencies_ready and sdk_version in tested and instrumentor_version == upstream}
    return {"dependencies": shared, "adapters": adapters}


def select_instrumentor(requested="auto", detected=None):
    if requested != "auto" and requested not in LAYERS:
        raise ConfigurationError("select_one_openinference_instrumentor")
    detected = detected_openinference() if detected is None else detected
    if requested != "auto":
        return requested if detected["adapters"][requested]["supported"] else None
    return next((name for name in LAYERS if detected["adapters"][name]["supported"]), None)


class _NoUploads:
    """Explicit object prevents OpenInference loading an environment plugin."""
    def upload(self, _blob):
        return None

    def shutdown(self, timeout_sec=None):
        return None


def _privacy_config():
    from openinference.instrumentation import TraceConfig
    return TraceConfig(hide_inputs=True, hide_outputs=True,
        hide_input_messages=True, hide_output_messages=True, hide_input_images=True,
        hide_input_text=True, hide_output_text=True, hide_llm_invocation_parameters=True,
        hide_llm_tools=True, hide_prompts=True, hide_choices=True,
        hide_embedding_vectors=True, hide_embeddings_vectors=True, hide_embeddings_text=True,
        enable_genai_semconv=False, base64_image_max_length=1, blob_uploader=_NoUploads())


def _legacy_id_generator(service_name):
    from opentelemetry import context
    from opentelemetry.sdk.trace.id_generator import RandomIdGenerator

    class ContextIdGenerator(RandomIdGenerator):
        def generate_trace_id(self):
            try:
                value = context.get_value("sillage.legacy_run_id")
            except BaseException:
                value = None
            if type(value) is str and _ID.fullmatch(value):
                # This creates the actual OTel root trace, never a fabricated
                # parent or export-time rewrite. Existing OTel parents win.
                source = "sillage:litellm:run:v1\0" + service_name + "\0" + value
                result = int.from_bytes(hashlib.sha256(source.encode("utf8")).digest()[:16], "big")
                return result or 1
            return super().generate_trace_id()
    return ContextIdGenerator()


class OpenInferenceRuntime:
    """One upstream owner layer, one private provider, one numeric processor."""
    def __init__(self, config, instrumentor="auto", exporter=None, diagnostic=None):
        self.config, self.requested = config, instrumentor
        self._exporter, self._diagnostic = exporter, diagnostic or (lambda _code: None)
        self._reported, self._hooks, self._shim_hooks = set(), [], []
        self._provider = self._processor = self._instrumentor = None
        self._pid = os.getpid()
        self._installed = self._closed = False
        self._result = None
        self.selected = None

    def _report(self, code):
        if code not in self._reported:
            self._reported.add(code)
            try:
                self._diagnostic(code)
            except BaseException:
                pass

    def _ensure_unowned(self):
        from .instrumentation import _ImportHook
        if any(isinstance(hook, _ImportHook) for hook in sys.meta_path):
            raise ConfigurationError("native_instrumentation_already_active")
        for name, (_sdk, _versions, _upstream, class_name) in LAYERS.items():
            module = sys.modules.get("openinference.instrumentation." + name)
            if module is not None:
                instrumentor_class = getattr(module, class_name, None)
                if instrumentor_class and instrumentor_class().is_instrumented_by_opentelemetry:
                    raise ConfigurationError("existing_instrumentor_use_span_processor")
        # Known overlapping OpenLLMetry instrumentation must keep its owner.
        for name, class_name in (("openai", "OpenAIInstrumentor"), ("litellm", "LiteLLMInstrumentor"),
                                 ("langchain", "LangchainInstrumentor")):
            module = sys.modules.get("opentelemetry.instrumentation." + name)
            cls = getattr(module, class_name, None) if module else None
            if cls and cls().is_instrumented_by_opentelemetry:
                raise ConfigurationError("existing_instrumentor_use_span_processor")

    def _capture_hooks(self):
        if self.selected == "openai":
            sdk = import_module("openai")
            self._hooks = [(sdk.OpenAI, "request", inspect.getattr_static(sdk.OpenAI, "request")),
                           (sdk.AsyncOpenAI, "request", inspect.getattr_static(sdk.AsyncOpenAI, "request"))]
        elif self.selected == "langchain":
            owner = import_module("langchain_core.callbacks").BaseCallbackManager
            self._hooks = [(owner, "__init__", inspect.getattr_static(owner, "__init__"))]
        else:
            sdk = import_module("litellm")
            self._hooks = [(sdk, name, getattr(sdk, name))
                           for name in self._instrumentor.original_litellm_funcs]

    def _install_litellm_context(self):
        from opentelemetry import context, trace
        sdk = import_module("litellm")

        def attach(kwargs):
            data = kwargs.get("metadata")
            if type(data) is not dict:
                return None
            agent, run = dict.get(data, "generation_name"), dict.get(data, "trace_id")
            current = context.get_current()
            if type(agent) is str and _LABEL.fullmatch(agent):
                current = context.set_value("sillage.agent.name", agent, current)
            if type(run) is str and _ID.fullmatch(run):
                current = context.set_value("sillage.legacy_run_id", run, current)
                if not trace.get_current_span().get_span_context().is_valid:
                    self._report("legacy_workflow_id_mapped_to_otel_trace")
            return context.attach(current)

        def safe_attach(kwargs):
            try:
                return attach(kwargs)
            except BaseException:
                self._report("context_unavailable")
                return None

        def safe_detach(token):
            if token is not None:
                try:
                    context.detach(token)
                except BaseException:
                    self._report("context_unavailable")

        def wrap(original, asynchronous):
            if asynchronous:
                @wraps(original)
                async def observed(*args, **kwargs):
                    token = safe_attach(kwargs)
                    try:
                        return await original(*args, **kwargs)
                    finally:
                        safe_detach(token)
            else:
                @wraps(original)
                def observed(*args, **kwargs):
                    token = safe_attach(kwargs)
                    try:
                        return original(*args, **kwargs)
                    finally:
                        safe_detach(token)
            return observed

        for name in ("completion", "acompletion"):
            original = getattr(sdk, name)
            observed = wrap(original, name == "acompletion")
            setattr(sdk, name, observed)
            self._shim_hooks.append((sdk, name, original, observed))

    def install(self):
        global _ACTIVE
        if self._installed:
            return self
        if self._closed:
            raise ConfigurationError("instrumentation_already_closed")
        self.selected = select_instrumentor(self.requested)
        if self.selected is None:
            raise ConfigurationError("no_supported_openinference_stack")
        with _LOCK:
            if _ACTIVE is not None:
                raise ConfigurationError("sillage_instrumentation_already_active")
            self._ensure_unowned()
            _ACTIVE = self
        try:
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider, SpanLimits
            from opentelemetry.sdk.trace.sampling import ALWAYS_ON, ParentBased
            from .otel import SillageSpanProcessor
            self._processor = SillageSpanProcessor(self.config, exporter=self._exporter,
                                                   diagnostic=self._diagnostic)
            self._provider = TracerProvider(resource=Resource({"service.name": self.config.service_name}),
                sampler=ParentBased(ALWAYS_ON), id_generator=_legacy_id_generator(self.config.service_name),
                span_limits=SpanLimits(max_attributes=64, max_events=0, max_links=0, max_attribute_length=512),
                shutdown_on_exit=False)
            self._provider.add_span_processor(self._processor)
            module = import_module("openinference.instrumentation." + self.selected)
            self._instrumentor = getattr(module, LAYERS[self.selected][3])()
            if self._instrumentor.is_instrumented_by_opentelemetry:
                raise ConfigurationError("existing_instrumentor_use_span_processor")
            self._instrumentor.instrument(tracer_provider=self._provider, config=_privacy_config(),
                                          raise_exception_on_conflict=True)
            if not self._instrumentor.is_instrumented_by_opentelemetry:
                raise ConfigurationError("upstream_instrumentation_unavailable")
            self._capture_hooks()
            if self.selected == "litellm":
                self._install_litellm_context()
            self._installed = True
            self._report("openinference_layer_" + self.selected)
            return self
        except BaseException:
            self.close()
            raise ConfigurationError("upstream_instrumentation_unavailable") from None

    def close(self, timeout=3):
        global _ACTIVE
        if self._closed:
            return self._result
        self._closed = True
        if os.getpid() != self._pid:
            return None
        try:
            changed = False
            for owner, name, original, observed in reversed(self._shim_hooks):
                if getattr(owner, name, None) is observed:
                    setattr(owner, name, original)
                else:
                    changed = True
            if self._hooks and not changed and all(inspect.getattr_static(owner, name, None) is value for owner, name, value in self._hooks):
                self._instrumentor.uninstrument()
            elif self._hooks:
                self._report("instrumentation_changed_during_run")
        except BaseException:
            self._report("instrumentation_cleanup_unconfirmed")
        try:
            if self._processor is not None:
                self._result = self._processor.close(timeout=timeout)
            if self._provider is not None:
                self._provider.shutdown()
        except BaseException:
            self._report("export_shutdown_unconfirmed")
        finally:
            with _LOCK:
                if _ACTIVE is self:
                    _ACTIVE = None
        return self._result
