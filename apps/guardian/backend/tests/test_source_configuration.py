"""Version selection is explicit and cannot silently downgrade a source."""
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from guardian.langfuse_client import LangfuseTraceSource, SourceReadError


@pytest.mark.parametrize("settings", [
    {"api_version": "auto"}, {"api_version": []},
    {"host": "https://public:secret@example.invalid"},
    {"host": "https://example.invalid?secret=invalid"},
    {"host": "https://example.invalid#fragment"},
    {"host": "file:///private"}, {"host": ""},
    {"host": "https://example.invalid:notaport"},
    {"host": "https://example.invalid:99999"}, {"host": "https://example.invalid:0"},
])
def test_invalid_source_configuration_fails_without_contact(settings):
    requests = []
    source = LangfuseTraceSource(
        public_key="test-public", secret_key="test-secret",
        transport=httpx.MockTransport(lambda request: requests.append(request)),
        **settings,
    )
    now = datetime.now(timezone.utc)
    result = source.fetch_generations(now - timedelta(hours=1), until=now)
    assert not source.available
    assert result.status == "failed"
    assert result.error_code == "invalid_configuration"
    assert requests == []


def test_default_v2_does_not_construct_export_sdk_or_allow_legacy_calls(monkeypatch):
    import langfuse

    def forbidden_sdk(**kwargs):
        raise AssertionError("A read-only v2 source must not initialize a tracing SDK")

    monkeypatch.setattr(langfuse, "Langfuse", forbidden_sdk)
    requests = []

    def receive(request):
        requests.append(request)
        return httpx.Response(200, json={"data": [], "meta": {}})

    source = LangfuseTraceSource(
        host="https://example.invalid/langfuse/", public_key="test-public",
        secret_key="test-secret", transport=httpx.MockTransport(receive),
    )
    try:
        assert source.available
        assert source.api_version == "v2"
        now = datetime.now(timezone.utc)
        assert source.fetch_generations(now - timedelta(hours=1), until=now).complete
        assert requests[0].url.path == "/langfuse/api/public/v2/observations"
        for operation in ("traces", "trace", "observations"):
            with pytest.raises(SourceReadError, match="invalid_query"):
                source.read_sdk(operation)
        assert len(requests) == 1
    finally:
        source.close()
