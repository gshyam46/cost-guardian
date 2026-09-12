"""Identity configuration, exact mutation headers and browser cookie contracts."""
from http.cookies import SimpleCookie
import json
import os
from types import SimpleNamespace

import pytest
from starlette.requests import Request
from starlette.responses import Response

from identity.errors import IdentityError
from identity import settings as settings_module
from identity.routes import _clear_cookie, _set_cookie, require_csrf
from identity.settings import load_settings
from identity.store import FLOW_SECONDS, SESSION_SECONDS


ENV = {
    "GUARDIAN_AUTH_MODE": "oidc", "GUARDIAN_OIDC_ISSUER": "https://identity.example.test/tenant/",
    "GUARDIAN_OIDC_CLIENT_ID": "guardian-client", "GUARDIAN_OIDC_CLIENT_SECRET": "private-config-secret",
    "GUARDIAN_PUBLIC_URL": "https://guardian.example.test", "GUARDIAN_ORGANIZATION_ID": "example-org",
    "GUARDIAN_PROJECT_ID": "example-project", "GUARDIAN_ENVIRONMENT": "staging",
    "GUARDIAN_PROJECT_NAME": "Example product", "GUARDIAN_CONNECTION_ID": "example-connection",
    "GUARDIAN_OIDC_MEMBERS_JSON": json.dumps([
        {"subject": "owner-subject", "name": "Owner Name", "role": "owner"},
        {"subject": "viewer-subject", "name": "Viewer Name", "role": "viewer"},
    ]),
}


@pytest.fixture(autouse=True)
def synthetic_identity_environment(monkeypatch):
    for name in list(os.environ):
        if name.startswith("GUARDIAN_OIDC_") or name in {
            "GUARDIAN_AUTH_MODE", "GUARDIAN_ALLOW_INSECURE_LOCAL_AUTH", "GUARDIAN_PUBLIC_URL",
            "GUARDIAN_UI_ORIGIN", "GUARDIAN_ORGANIZATION_ID", "GUARDIAN_PROJECT_ID",
            "GUARDIAN_ENVIRONMENT", "GUARDIAN_PROJECT_NAME", "GUARDIAN_CONNECTION_ID",
        }:
            monkeypatch.delenv(name)
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)


def assert_invalid():
    with pytest.raises(IdentityError) as caught:
        load_settings()
    assert caught.value.status_code == 503
    assert caught.value.code == "invalid_configuration"
    assert caught.value.headers["Cache-Control"] == "no-store"
    assert ENV["GUARDIAN_OIDC_CLIENT_SECRET"] not in str(caught.value)


def test_valid_config_has_exact_binding_and_no_secret_repr():
    settings = load_settings()
    assert settings.mode == "oidc"
    assert settings.issuer.endswith("/tenant/")  # issuer exactness matters to signed tokens
    assert settings.redirect_uri == "https://guardian.example.test/api/guardian/auth/callback"
    assert settings.ui_origin == settings.public_url
    assert settings.binding == {"organization_id": "example-org", "project_id": "example-project",
                                "environment": "staging", "connection_id": "example-connection",
                                "issuer": ENV["GUARDIAN_OIDC_ISSUER"], "client_id": "guardian-client"}
    assert ENV["GUARDIAN_OIDC_CLIENT_SECRET"] not in repr(settings)
    assert "owner-subject" not in repr(settings)
    assert "private-config-secret" not in json.dumps(settings.binding)


def test_legacy_mode_does_not_require_provider_configuration(monkeypatch):
    for name in ENV:
        monkeypatch.delenv(name, raising=False)
    assert load_settings().mode == "api_key"
    monkeypatch.setenv("GUARDIAN_OIDC_MEMBERS_JSON", "malformed-but-inactive")
    assert load_settings().mode == "api_key"


@pytest.mark.parametrize("mode", ["", "OIDC", "oidc ", "unknown", "cookie"])
def test_unknown_auth_mode_fails_closed(monkeypatch, mode):
    monkeypatch.setenv("GUARDIAN_AUTH_MODE", mode)
    assert_invalid()


@pytest.mark.parametrize("missing", [name for name in ENV if name not in {"GUARDIAN_AUTH_MODE", "GUARDIAN_CONNECTION_ID"}])
def test_missing_required_configuration(monkeypatch, missing):
    monkeypatch.delenv(missing)
    assert_invalid()


@pytest.mark.parametrize("key,value", [
    ("GUARDIAN_OIDC_ISSUER", "http://identity.example.test"),
    ("GUARDIAN_OIDC_ISSUER", "https://user:secret@identity.example.test"),
    ("GUARDIAN_OIDC_ISSUER", "https://identity.example.test:99999"),
    ("GUARDIAN_OIDC_ISSUER", "https://identity.example.test:badport"),
    ("GUARDIAN_OIDC_ISSUER", "https://identity.example.test:0"),
    ("GUARDIAN_OIDC_ISSUER", "https://identity.example.test/path?unexpected=private"),
    ("GUARDIAN_OIDC_ISSUER", "https://identity.example.test/path#fragment"),
    ("GUARDIAN_OIDC_ISSUER", "https://identity.example.test?"),
    ("GUARDIAN_PUBLIC_URL", "https://guardian.example.test#"),
    ("GUARDIAN_OIDC_ISSUER", " https://identity.example.test"),
    ("GUARDIAN_OIDC_ISSUER", "https://identity.exam ple.test"),
    ("GUARDIAN_OIDC_ISSUER", "https://identity.example.test/a b"),
    ("GUARDIAN_PUBLIC_URL", "https://guardian.example.test/app"),
    ("GUARDIAN_PUBLIC_URL", "https://guardian.example.test/\\other"),
    ("GUARDIAN_UI_ORIGIN", "https://another.example.test"),
    ("GUARDIAN_PROJECT_ID", "project/another"),
    ("GUARDIAN_ORGANIZATION_ID", " org"),
    ("GUARDIAN_ENVIRONMENT", "prod\nlog"),
    ("GUARDIAN_CONNECTION_ID", "connection:name"),
    ("GUARDIAN_OIDC_CLIENT_SECRET", ""),
    ("GUARDIAN_OIDC_CLIENT_ID", "   "),
    ("GUARDIAN_PROJECT_NAME", "   "),
    ("GUARDIAN_ALLOW_INSECURE_LOCAL_AUTH", "yes"),
    ("GUARDIAN_ALLOW_INSECURE_LOCAL_AUTH", "TRUE"),
])
def test_malformed_urls_and_scope_configuration(monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    assert_invalid()


@pytest.mark.parametrize("public,ui,expected", [
    ("HTTPS://GUARDIAN.example.test:443/", "https://guardian.example.test", "https://guardian.example.test"),
    ("https://guardian.example.test", "HTTPS://GUARDIAN.example.test:443/", "https://guardian.example.test"),
    ("https://GUARDIAN.example.test:8443", "https://guardian.example.test:8443/", "https://guardian.example.test:8443"),
    ("https://[2001:0DB8:0000:0000:0000:0000:0000:0001]:443", "https://[2001:db8::1]", "https://[2001:db8::1]"),
    ("https://[2001:db8::1]:8443", "https://[2001:0db8::1]:8443/", "https://[2001:db8::1]:8443"),
    ("https://XN--BCHER-KVA.example:443", "https://xn--bcher-kva.example/", "https://xn--bcher-kva.example"),
])
def test_browser_origin_canonicalization_preserves_exact_issuer(monkeypatch, public, ui, expected):
    exact_issuer = "HTTPS://IDENTITY.example.test:443/tenant/"
    monkeypatch.setenv("GUARDIAN_OIDC_ISSUER", exact_issuer)
    monkeypatch.setenv("GUARDIAN_PUBLIC_URL", public)
    monkeypatch.setenv("GUARDIAN_UI_ORIGIN", ui)
    settings = load_settings()
    assert settings.public_url == settings.ui_origin == expected
    assert settings.redirect_uri == expected + "/api/guardian/auth/callback"
    assert settings.issuer == exact_issuer and settings.binding["issuer"] == exact_issuer
    require_csrf(request([("Origin", expected), ("X-Guardian-CSRF", "a" * 43)]),
                 settings, SimpleNamespace(csrf_token="a" * 43))


def test_loopback_origin_canonicalization_removes_http_default_port(monkeypatch):
    monkeypatch.setenv("GUARDIAN_ALLOW_INSECURE_LOCAL_AUTH", "true")
    monkeypatch.setenv("GUARDIAN_OIDC_ISSUER", "http://localhost:9000/tenant")
    monkeypatch.setenv("GUARDIAN_PUBLIC_URL", "HTTP://[0:0:0:0:0:0:0:1]:80/")
    monkeypatch.setenv("GUARDIAN_UI_ORIGIN", "http://LOCALHOST:3001/")
    settings = load_settings()
    assert settings.public_url == "http://[::1]"
    assert settings.ui_origin == "http://localhost:3001"
    assert settings.redirect_uri == "http://[::1]/api/guardian/auth/callback"


@pytest.mark.parametrize("url", [
    "https://guardian.example.test.", "https://guardian..example.test", "https://bad_host.example.test",
    "https://guardian.example.test:", "https://b\u00fccher.example", "https://%67uardian.example.test",
    "https://127.1", "https://2130706433", "https://0x7f.0.0.1", "https://127.000.000.1",
    "https://[fe80::1%25scope]", "https://[v1.example]",
])
def test_unsupported_browser_origin_host_syntax_fails_configuration(monkeypatch, url):
    monkeypatch.setenv("GUARDIAN_PUBLIC_URL", url)
    assert_invalid()


@pytest.mark.parametrize("entries", [None, {}, [], [None],
    [{"subject": "viewer", "name": "Only viewer", "role": "viewer"}],
    [{"subject": "subject", "name": "Name", "role": "admin"}],
    [{"subject": "subject", "name": "Name", "role": "owner", "email": "untrusted@example.test"}],
    [{"subject": "subject", "name": "Name", "role": "owner"}, {"subject": "subject", "name": "Duplicate", "role": "viewer"}],
    [{"subject": "", "name": "Name", "role": "owner"}],
    [{"subject": "non-ascii-\u00e9", "name": "Name", "role": "owner"}],
    [{"subject": "subject", "name": "unsafe\nname", "role": "owner"}],
    [{"subject": "subject", "name": "   ", "role": "owner"}],
    [{"subject": "   ", "name": "Name", "role": "owner"}],
    [{"subject": ["subject"], "name": "Name", "role": "owner"}],
])
def test_membership_is_explicit_bounded_unique_and_requires_owner(monkeypatch, entries):
    monkeypatch.setenv("GUARDIAN_OIDC_MEMBERS_JSON", json.dumps(entries))
    assert_invalid()


@pytest.mark.parametrize("raw", ["not-json", "x" * 65537, "[" * 1500 + "]" * 1500],
                         ids=["invalid_json", "over_limit", "nested"])
def test_bad_or_deep_membership_json_remains_safe_configuration_error(monkeypatch, raw):
    # Windows rejects a real environment value this long before the parser can
    # inspect it. Inject only this module's environment view, without OS writes.
    environment = {**os.environ, "GUARDIAN_OIDC_MEMBERS_JSON": raw}
    monkeypatch.setattr(settings_module, "os", SimpleNamespace(environ=environment, getenv=environment.get))
    assert_invalid()


def test_member_count_bound(monkeypatch):
    monkeypatch.setenv("GUARDIAN_OIDC_MEMBERS_JSON", json.dumps([
        {"subject": f"subject-{index}", "name": "Name", "role": "owner"} for index in range(101)
    ]))
    assert_invalid()


def test_local_exception_requires_all_origins_loopback(monkeypatch):
    monkeypatch.setenv("GUARDIAN_ALLOW_INSECURE_LOCAL_AUTH", "true")
    assert_invalid()  # cannot weaken cookies while retaining production hosts
    monkeypatch.setenv("GUARDIAN_OIDC_ISSUER", "http://localhost:9000/tenant")
    monkeypatch.setenv("GUARDIAN_PUBLIC_URL", "http://127.0.0.1:8001/")
    monkeypatch.setenv("GUARDIAN_UI_ORIGIN", "http://localhost:3001/")
    settings = load_settings()
    assert settings.public_url == "http://127.0.0.1:8001"
    assert settings.ui_origin == "http://localhost:3001"
    assert settings.session_cookie == "guardian_session" and settings.login_cookie == "guardian_login"
    assert settings.secure_cookies is False
    monkeypatch.setenv("GUARDIAN_OIDC_ISSUER", "http://127.0.0.1.attacker.test")
    assert_invalid()


def test_production_session_and_login_cookies_have_host_bound_security_options():
    settings = load_settings()
    assert settings.session_cookie == "__Host-guardian_session"
    assert settings.login_cookie == "__Host-guardian_login"
    for name, lifetime in ((settings.session_cookie, SESSION_SECONDS), (settings.login_cookie, FLOW_SECONDS)):
        response = Response()
        _set_cookie(response, settings, name, "synthetic-opaque-value", lifetime)
        cookie = SimpleCookie(response.headers["set-cookie"])[name]
        assert cookie["secure"] and cookie["httponly"]
        assert cookie["samesite"].lower() == "lax" and cookie["path"] == "/"
        assert cookie["domain"] == "" and int(cookie["max-age"]) == lifetime
        response = Response()
        _clear_cookie(response, settings, name)
        removed = SimpleCookie(response.headers["set-cookie"])[name]
        assert removed["secure"] and removed["httponly"] and removed["path"] == "/"
        assert removed["samesite"].lower() == "lax" and removed["domain"] == ""
        assert int(removed["max-age"]) == 0


def request(headers):
    return Request({"type": "http", "method": "POST", "path": "/api/guardian/auth/logout",
                    "headers": [(key.lower().encode("ascii"), value.encode("latin1")) for key, value in headers]})


def test_exact_origin_and_csrf_header_succeeds():
    settings = load_settings()
    principal = SimpleNamespace(csrf_token="a" * 43)
    require_csrf(request([("Origin", settings.ui_origin), ("X-Guardian-CSRF", principal.csrf_token)]), settings, principal)


@pytest.mark.parametrize("headers", [
    [], [("origin", "https://guardian.example.test")], [("x-guardian-csrf", "a" * 43)],
    [("origin", "https://attacker.example.test"), ("x-guardian-csrf", "a" * 43)],
    [("origin", "https://guardian.example.test/"), ("x-guardian-csrf", "a" * 43)],
    [("origin", "null"), ("x-guardian-csrf", "a" * 43)],
    [("origin", "https://guardian.example.test"), ("origin", "https://guardian.example.test"), ("x-guardian-csrf", "a" * 43)],
    [("origin", "https://guardian.example.test"), ("x-guardian-csrf", "a" * 43), ("x-guardian-csrf", "a" * 43)],
    [("origin", "https://guardian.example.test"), ("x-guardian-csrf", "\xff" * 43)],
    [("origin", "https://guardian.example.test"), ("x-guardian-csrf", "a" * 257)],
    [("origin", "https://guardian.example.test"), ("x-guardian-csrf", "a" * 43 + "," + "a" * 43)],
])
def test_missing_duplicate_unicode_and_wrong_origin_csrf_headers_deny(headers):
    with pytest.raises(IdentityError) as caught:
        require_csrf(request(headers), load_settings(), SimpleNamespace(csrf_token="a" * 43))
    assert caught.value.status_code == 403
    assert caught.value.code == "invalid_csrf"
