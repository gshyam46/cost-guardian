"""The actual Uvicorn formatter must never render callback credentials."""
import logging

import httpx
import httpx2
import pytest
from uvicorn.logging import AccessFormatter

from identity.logging import CallbackQueryFilter, install_callback_log_filter


CODE = "synthetic-private-code"
STATE = "synthetic-private-state"
QUERY = f"code={CODE}&state={STATE}&error_description=synthetic-private-description"


def uvicorn_record(path):
    return logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1,
                             '%s - "%s %s HTTP/%s" %d',
                             ("127.0.0.1:12345", "GET", path, "1.1", 303), None)


def formatted(record):
    CallbackQueryFilter().filter(record)
    return AccessFormatter('%(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False).format(record)


@pytest.mark.parametrize("path", ["/api/guardian/auth/callback", "/api/guardian/auth/callback/",
                                  "/api/guardian/auth/%63allback", "/api/guardian/auth/callback%2F"])
def test_actual_uvicorn_formatter_redacts_canonical_encoded_and_slash_redirect_queries(path):
    record = uvicorn_record(path + "?" + QUERY)
    output = formatted(record)
    for private in (CODE, STATE, "synthetic-private-description"):
        assert private not in output
        assert private not in record.getMessage()
    assert isinstance(record.args, tuple) and len(record.args) == 5
    assert "303 See Other" in output and "GET" in output


@pytest.mark.parametrize("library", [httpx, httpx2])
@pytest.mark.parametrize("path", ["/api/guardian/auth/callback", "/api/guardian/auth/callback/", "/api/guardian/auth/%63allback"])
def test_http_client_callback_records_remove_query_without_logging_token(library, path):
    record = logging.LogRecord(library.__name__, logging.INFO, __file__, 1,
                              'HTTP Request: %s %s "%s %d %s"',
                              ("GET", library.URL("https://guardian.example.test" + path + "?" + QUERY), "HTTP/1.1", 303, "See Other"), None)
    CallbackQueryFilter().filter(record)
    output = logging.Formatter("%(message)s").format(record)
    assert CODE not in output and STATE not in output and "synthetic-private-description" not in output
    assert "303" in output


@pytest.mark.parametrize("library", [httpx, httpx2])
def test_http_client_literal_apostrophe_query_does_not_split_redaction(library):
    url = library.URL("https://guardian.example.test/api/guardian/auth/callback?code=prefix'" + CODE + "&state=" + STATE)
    assert "'" in str(url)  # accepted URI character, not a quoted log delimiter
    record = logging.LogRecord(library.__name__, logging.INFO, __file__, 1,
                              'HTTP Request: %s %s "%s %d %s"',
                              ("GET", url, "HTTP/1.1", 303, "See Other"), None)
    CallbackQueryFilter().filter(record)
    assert CODE not in record.getMessage() and STATE not in record.getMessage()


def test_non_callback_access_diagnostics_and_formatter_args_are_unchanged():
    record = uvicorn_record("/api/guardian/incidents?status=open")
    original = record.args
    output = formatted(record)
    assert record.args == original
    assert "/api/guardian/incidents?status=open" in output


def test_preformatted_callback_message_is_redacted():
    record = logging.LogRecord("httpx", logging.INFO, __file__, 1,
                              "GET https://guardian.example.test/api/guardian/auth/callback?" + QUERY, (), None)
    CallbackQueryFilter().filter(record)
    assert CODE not in record.getMessage() and STATE not in record.getMessage()


def test_filter_install_is_idempotent_on_actual_target_loggers():
    install_callback_log_filter()
    install_callback_log_filter()
    for name in ("uvicorn.access", "httpx", "httpx2"):
        assert sum(isinstance(item, CallbackQueryFilter) for item in logging.getLogger(name).filters) == 1
