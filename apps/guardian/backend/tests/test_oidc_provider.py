"""Real signatures over a synthetic HTTP provider; never contact an account."""
import asyncio
import base64
import hashlib
import json
import logging
import time
from urllib.parse import parse_qs, urlsplit

import httpx2
from joserfc import jwt
from joserfc.jwk import OctKey, RSAKey
import pytest

from identity import oidc_provider as module
from identity.oidc_provider import OIDCProvider, ProviderError


ISSUER = "https://identity.example.test/tenant"
CALLBACK = "https://guardian.example.test/api/guardian/auth/callback"
CLIENT_ID = "guardian-test-client"
CLIENT_SECRET = "synthetic-client-secret"
NONCE = "n" * 43
STATE = "s" * 43
VERIFIER = "v" * 64
CODE = "synthetic-authorization-code"
ACCESS_TOKEN = "synthetic-provider-access-token"
STATE_DATA = {"nonce": NONCE, "code_verifier": VERIFIER}
pytestmark = pytest.mark.anyio


@pytest.fixture(scope="module")
def signing_key():
    return RSAKey.generate_key(2048, parameters={"kid": "test-key", "use": "sig", "alg": "RS256"})


def claims(**changes):
    now = int(time.time())
    return {"iss": ISSUER, "sub": "subject-123", "aud": CLIENT_ID,
            "iat": now - 2, "exp": now + 300, "nonce": NONCE,
            "name": "Example Operator", "email": "not-an-identity@example.test", **changes}


def discovery(**changes):
    return {"issuer": ISSUER, "authorization_endpoint": ISSUER + "/authorize",
            "token_endpoint": ISSUER + "/token", "jwks_uri": ISSUER + "/jwks",
            "response_types_supported": ["code"], "id_token_signing_alg_values_supported": ["RS256"],
            "token_endpoint_auth_methods_supported": ["client_secret_basic"],
            "code_challenge_methods_supported": ["S256"], **changes}


class ProviderFixture:
    def __init__(self, key, *, payload=None, metadata=None, key_set=None, encoded=None):
        self.key = key
        self.payload = payload if payload is not None else claims()
        self.metadata = metadata if metadata is not None else discovery()
        self.keys = key_set if key_set is not None else {"keys": [key.as_dict()]}
        self.encoded = encoded
        self.requests = []
        self.responses = {}
        self.token_changes = {}

    def handler(self, request):
        self.requests.append(request)
        response = self.responses.get(request.url.path)
        if response is not None:
            if isinstance(response, Exception):
                raise response
            return response
        if request.url.path.endswith("/.well-known/openid-configuration"):
            return httpx2.Response(200, json=self.metadata)
        if request.url.path.endswith("/jwks"):
            return httpx2.Response(200, json=self.keys)
        if request.url.path.endswith("/token"):
            encoded = self.encoded or jwt.encode({"alg": "RS256", "kid": "test-key"}, self.payload, self.key)
            return httpx2.Response(200, json={"id_token": encoded, "access_token": ACCESS_TOKEN,
                                             "token_type": "Bearer", "refresh_token": "discard-refresh", **self.token_changes})
        raise AssertionError("Unexpected provider endpoint")

    def provider(self, **options):
        return OIDCProvider(ISSUER, CLIENT_ID, CLIENT_SECRET, CALLBACK,
                            transport=httpx2.MockTransport(self.handler), **options)


async def test_public_authlib_code_flow_pkce_and_minimal_verified_identity(signing_key, monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://ambient-proxy.invalid:9999")
    monkeypatch.setenv("SSL_CERT_FILE", "untrusted-ambient-certificate")
    fixture = ProviderFixture(signing_key)
    provider = fixture.provider()
    authorization = await provider.start(STATE, NONCE, VERIFIER)
    parsed = urlsplit(authorization)
    query = parse_qs(parsed.query)
    assert parsed.scheme == "https" and parsed.path == "/tenant/authorize"
    assert query == {"response_type": ["code"], "client_id": [CLIENT_ID], "redirect_uri": [CALLBACK],
                     "scope": ["openid profile"], "state": [STATE], "nonce": [NONCE],
                     "code_challenge": [base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).decode().rstrip("=")],
                     "code_challenge_method": ["S256"], "response_mode": ["query"]}
    assert VERIFIER not in authorization and CLIENT_SECRET not in authorization
    identity = await provider.finish(CODE, STATE_DATA)
    assert identity == {"issuer": ISSUER, "subject": "subject-123", "name": "Example Operator"}
    assert "email" not in identity and "token" not in json.dumps(identity)
    assert len(fixture.requests) == 4  # discovery for start, then discovery/token/JWKS
    request = next(request for request in fixture.requests if request.method == "POST")
    assert request.url.path == "/tenant/token" and not request.url.query
    assert request.headers["Authorization"] == "Basic " + base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    assert parse_qs(request.content.decode()) == {"grant_type": ["authorization_code"], "code": [CODE],
                                                  "code_verifier": [VERIFIER], "redirect_uri": [CALLBACK]}
    for request in fixture.requests:
        assert request.headers["accept-encoding"] == "identity"
        assert all(value <= 5 for value in request.extensions["timeout"].values())
        if request.method == "GET":
            assert "authorization" not in request.headers


@pytest.mark.parametrize("change", [
    {"iss": "https://different.example.test"}, {"aud": "another-client"},
    {"aud": ["another-client", CLIENT_ID]}, {"azp": "another-client"}, {"azp": ""},
    {"aud": []}, {"aud": [CLIENT_ID, 7]}, {"sub": ""}, {"sub": 7},
    {"sub": "x" * 256}, {"sub": "subject\nlog"},
    {"nonce": "incorrect-nonce"}, {"nonce": None}, {"nonce": 5},
    {"nonce": "incorrect-nonce", "nonce_supported": False},
    {"iat": 9999999999}, {"iat": True}, {"iat": float("nan")},
    {"exp": 1}, {"exp": True}, {"exp": float("inf")}, {"exp": "9999999999"},
    {"nbf": 9999999999}, {"nbf": False}, {"at_hash": "wrong-token-hash"}, {"at_hash": ""},
])
async def test_signed_but_invalid_claims_fail_closed(signing_key, change):
    fixture = ProviderFixture(signing_key, payload=claims(**change))
    with pytest.raises(ProviderError, match="^invalid_id_token$"):
        await fixture.provider().finish(CODE, STATE_DATA)


@pytest.mark.parametrize("missing", ["iss", "sub", "aud", "exp", "iat", "nonce"])
async def test_missing_required_signed_claim(signing_key, missing):
    payload = claims(nonce_supported=False)
    payload.pop(missing)
    fixture = ProviderFixture(signing_key, payload=payload)
    with pytest.raises(ProviderError, match="^invalid_id_token$"):
        await fixture.provider().finish(CODE, STATE_DATA)


async def test_valid_multiple_audience_azp_at_hash_and_false_nonce_hint(signing_key):
    half_hash = base64.urlsafe_b64encode(hashlib.sha256(ACCESS_TOKEN.encode()).digest()[:16]).decode().rstrip("=")
    fixture = ProviderFixture(signing_key, payload=claims(aud=[CLIENT_ID, "another-client"], azp=CLIENT_ID,
                                                        at_hash=half_hash, nonce_supported=False))
    assert (await fixture.provider().finish(CODE, STATE_DATA))["subject"] == "subject-123"


@pytest.mark.parametrize("name", [None, [], {"unexpected": "object"}, "x" * 201, "unsafe\nname", "   "])
async def test_optional_name_is_bounded_without_inventing_email_identity(signing_key, name):
    fixture = ProviderFixture(signing_key, payload=claims(name=name))
    assert (await fixture.provider().finish(CODE, STATE_DATA))["name"] is None


@pytest.mark.parametrize("kind", ["wrong_signature", "none", "HS256", "RS512", "bad_format", "unknown_kid", "embedded_attacker_key"])
async def test_signatures_algorithms_and_untrusted_keys(signing_key, kind):
    header = {"alg": "RS256", "kid": "test-key"}
    if kind in {"wrong_signature", "embedded_attacker_key"}:
        attacker = RSAKey.generate_key(2048)
        if kind == "embedded_attacker_key":
            header.update(jwk=attacker.as_dict(), jku="https://attacker.invalid/jwks")
        encoded = jwt.encode(header, claims(), attacker)
    elif kind == "none":
        b64 = lambda value: base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")
        encoded = b64({"alg": "none"}) + "." + b64(claims()) + "."
    elif kind == "HS256":
        encoded = jwt.encode({"alg": "HS256", "kid": "test-key"}, claims(), OctKey.generate_key(256))
    elif kind == "RS512":
        raw = signing_key.as_dict(private=True)
        raw.pop("alg", None)
        other = RSAKey.import_key(raw)
        encoded = jwt.encode({"alg": "RS512", "kid": "test-key"}, claims(), other, algorithms=["RS512"])
    elif kind == "unknown_kid":
        encoded = jwt.encode({"alg": "RS256", "kid": "not-discovered"}, claims(), signing_key)
    else:
        encoded = "not-a-jwt"
    fixture = ProviderFixture(signing_key, encoded=encoded)
    with pytest.raises(ProviderError, match="^invalid_id_token$"):
        await fixture.provider().finish(CODE, STATE_DATA)
    assert len(fixture.requests) == 3
    assert all(request.url.host == "identity.example.test" for request in fixture.requests)


@pytest.mark.parametrize("key_set", [None, [], {}, {"keys": []}, {"keys": [None]}, {"keys": [{"kty": "oct", "k": "a"}]}])
async def test_malformed_jwks(signing_key, key_set):
    fixture = ProviderFixture(signing_key)
    fixture.responses["/tenant/jwks"] = httpx2.Response(200, json=key_set)
    with pytest.raises(ProviderError):
        await fixture.provider().finish(CODE, STATE_DATA)


async def test_duplicate_key_ids_and_private_or_oversized_keys_rejected(signing_key):
    for keys in ([signing_key.as_dict(), signing_key.as_dict()], [signing_key.as_dict(private=True)],
                 [{**signing_key.as_dict(), "n": "A" * 1401}], [signing_key.as_dict()] * 33):
        fixture = ProviderFixture(signing_key, key_set={"keys": keys})
        with pytest.raises(ProviderError, match="^invalid_id_token$"):
            await fixture.provider().finish(CODE, STATE_DATA)


async def test_signing_key_rotation_is_read_fresh_without_cached_old_jwks(signing_key):
    fixture = ProviderFixture(signing_key)
    provider = fixture.provider()
    await provider.start(STATE, NONCE, VERIFIER)
    assert (await provider.finish(CODE, STATE_DATA))["subject"] == "subject-123"
    rotated = RSAKey.generate_key(2048, parameters={"kid": "rotated-key", "use": "sig", "alg": "RS256"})
    fixture.keys = {"keys": [rotated.as_dict()]}
    fixture.encoded = jwt.encode({"alg": "RS256", "kid": "rotated-key"}, claims(sub="rotated-subject"), rotated)
    assert (await provider.finish(CODE, STATE_DATA))["subject"] == "rotated-subject"
    assert sum(request.url.path.endswith("/jwks") for request in fixture.requests) == 2


@pytest.mark.parametrize("changes", [
    {"id_token": None}, {"id_token": []}, {"id_token": "x" * 32769},
    {"access_token": None}, {"access_token": []}, {"token_type": "other"}, {"token_type": None},
])
async def test_invalid_token_response_fields_fail_before_jwks(signing_key, changes):
    fixture = ProviderFixture(signing_key)
    fixture.token_changes = changes
    with pytest.raises(ProviderError, match="^invalid_id_token$"):
        await fixture.provider().finish(CODE, STATE_DATA)
    assert len(fixture.requests) == 2


@pytest.mark.parametrize("change", [
    {"issuer": ISSUER + "/other"}, {"authorization_endpoint": "http://identity.example.test/auth"},
    {"token_endpoint": "https://user:secret@identity.example.test/token"},
    {"jwks_uri": "https://identity.example.test:99999/jwks"},
    {"jwks_uri": "https://identity.example.test/jwks?secret=private"},
    {"token_endpoint": "https://identity.example.test/token#fragment"},
    {"response_types_supported": ["token"]}, {"id_token_signing_alg_values_supported": ["none"]},
    {"token_endpoint_auth_methods_supported": ["client_secret_post"]},
    {"code_challenge_methods_supported": ["plain"]},
])
async def test_untrusted_or_unsupported_discovery_never_exchanges_code(signing_key, change):
    fixture = ProviderFixture(signing_key, metadata=discovery(**change))
    with pytest.raises(ProviderError, match="^invalid_provider_metadata$"):
        await fixture.provider().finish(CODE, STATE_DATA)
    assert len(fixture.requests) == 1


@pytest.mark.parametrize("location", ["/.well-known/openid-configuration", "/token", "/jwks"])
async def test_no_redirects_followed(signing_key, location):
    fixture = ProviderFixture(signing_key)
    fixture.responses["/tenant" + location] = httpx2.Response(302, headers={"Location": "https://attacker.invalid/steal"})
    with pytest.raises(ProviderError, match="^provider_unavailable$"):
        await fixture.provider().finish(CODE, STATE_DATA)
    assert all(request.url.host == "identity.example.test" for request in fixture.requests)


@pytest.mark.parametrize("status,expected", [(400, "token_exchange_failed"), (401, "token_exchange_failed"),
                                              (403, "token_exchange_failed"), (429, "provider_unavailable"), (503, "provider_unavailable")])
async def test_provider_error_bodies_do_not_escape(signing_key, status, expected, caplog):
    fixture = ProviderFixture(signing_key)
    fixture.responses["/tenant/token"] = httpx2.Response(status, json={"error": "private-code", "error_description": CLIENT_SECRET + CODE})
    with pytest.raises(ProviderError) as error:
        await fixture.provider().finish(CODE, STATE_DATA)
    assert str(error.value) == expected
    assert error.value.__cause__ is None
    assert CLIENT_SECRET not in caplog.text and CODE not in caplog.text


async def test_http_and_core_logs_are_redacted_only_during_provider_io(signing_key, caplog):
    caplog.set_level(logging.DEBUG)
    fixture = ProviderFixture(signing_key)
    original = fixture.handler
    def handler(request):
        logging.getLogger("httpcore2.http11").debug("response headers %s", {"private": CLIENT_SECRET + CODE + STATE})
        response = original(request)
        response.extensions["reason_phrase"] = (CLIENT_SECRET + NONCE).encode()
        return response
    provider = OIDCProvider(ISSUER, CLIENT_ID, CLIENT_SECRET, CALLBACK, transport=httpx2.MockTransport(handler))
    await provider.finish(CODE, STATE_DATA)
    for secret in (CLIENT_SECRET, CODE, STATE, NONCE, ACCESS_TOKEN, "discard-refresh"):
        assert secret not in caplog.text
    assert "OIDC provider transport event" in caplog.text
    logging.getLogger("httpx2").info("unrelated diagnostic retained")
    assert "unrelated diagnostic retained" in caplog.text


class ChunkStream(httpx2.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk

    async def aclose(self):
        self.closed = True


async def test_actual_stream_byte_bound_and_cleanup(signing_key, monkeypatch):
    monkeypatch.setattr(module, "MAX_RESPONSE_BYTES", 128)
    stream = ChunkStream([b" " * 70, b" " * 70])
    fixture = ProviderFixture(signing_key)
    fixture.responses["/tenant/.well-known/openid-configuration"] = httpx2.Response(200, stream=stream)
    with pytest.raises(ProviderError, match="^provider_unavailable$"):
        await fixture.provider().start(STATE, NONCE, VERIFIER)
    assert stream.closed
    assert len(fixture.requests) == 1


@pytest.mark.parametrize("headers", [{"Content-Encoding": "gzip"}, {"Content-Length": "1048577"}])
async def test_encoded_or_oversized_responses_rejected_before_read(signing_key, headers):
    stream = ChunkStream([b"provider-controlled-body"])
    fixture = ProviderFixture(signing_key)
    fixture.responses["/tenant/.well-known/openid-configuration"] = httpx2.Response(200, headers=headers, stream=stream)
    with pytest.raises(ProviderError, match="^provider_unavailable$"):
        await fixture.provider().start(STATE, NONCE, VERIFIER)
    assert stream.closed


async def test_http_timeout_is_safe_and_not_retried(signing_key):
    fixture = ProviderFixture(signing_key)
    fixture.responses["/tenant/token"] = httpx2.ReadTimeout(CLIENT_SECRET + CODE)
    with pytest.raises(ProviderError, match="^provider_timeout$"):
        await fixture.provider().finish(CODE, STATE_DATA)
    assert len(fixture.requests) == 2


async def test_total_deadline_cancels_provider_request_and_closes_transport(monkeypatch):
    monkeypatch.setattr(module, "OPERATION_TIMEOUT_SECONDS", 0.03)
    class SlowTransport(httpx2.AsyncBaseTransport):
        cancelled = False
        closed = False
        async def handle_async_request(self, request):
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                self.cancelled = True
                raise
        async def aclose(self):
            self.closed = True
    transport = SlowTransport()
    provider = OIDCProvider(ISSUER, CLIENT_ID, CLIENT_SECRET, CALLBACK, transport=transport)
    with pytest.raises(ProviderError, match="^provider_timeout$"):
        await provider.start(STATE, NONCE, VERIFIER)
    assert transport.cancelled and transport.closed


@pytest.mark.parametrize("kwargs", [
    {"issuer": "http://identity.example.test"}, {"redirect_uri": "http://guardian.example.test/callback"},
    {"issuer": "https://identity.example.test:badport"}, {"issuer": "https://identity.example.test:0"},
    {"issuer": "https://identity.example.test/path?unexpected=yes"}, {"client_secret": ""},
    {"issuer": "https://identity.example.test?"}, {"redirect_uri": CALLBACK + "#"},
    {"allow_loopback_http": "true"},
])
async def test_invalid_configuration_fails_before_network(kwargs):
    args = {"issuer": ISSUER, "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, "redirect_uri": CALLBACK, **kwargs}
    with pytest.raises(ProviderError, match="^invalid_configuration$"):
        OIDCProvider(**args)


async def test_loopback_http_requires_explicit_development_flag():
    for issuer in ("http://localhost:9000", "http://127.0.0.1:9000", "http://[::1]:9000"):
        with pytest.raises(ProviderError):
            OIDCProvider(issuer, CLIENT_ID, CLIENT_SECRET, "http://localhost:8001/api/guardian/auth/callback")
        provider = OIDCProvider(issuer, CLIENT_ID, CLIENT_SECRET, "http://localhost:8001/api/guardian/auth/callback", allow_loopback_http=True)
        assert provider.issuer == issuer
    with pytest.raises(ProviderError):
        OIDCProvider("http://192.168.1.1", CLIENT_ID, CLIENT_SECRET, CALLBACK, allow_loopback_http=True)


async def test_explicit_loopback_development_completes_signed_code_flow(signing_key):
    issuer = "http://localhost:9000/tenant"
    callback = "http://127.0.0.1:8001/api/guardian/auth/callback"
    fixture = ProviderFixture(signing_key, payload=claims(iss=issuer), metadata=discovery(
        issuer=issuer, authorization_endpoint=issuer + "/authorize",
        token_endpoint=issuer + "/token", jwks_uri=issuer + "/jwks",
    ))
    provider = OIDCProvider(issuer, CLIENT_ID, CLIENT_SECRET, callback, allow_loopback_http=True,
                            transport=httpx2.MockTransport(fixture.handler))
    assert (await provider.start(STATE, NONCE, VERIFIER)).startswith(issuer + "/authorize?")
    assert (await provider.finish(CODE, STATE_DATA))["issuer"] == issuer


async def test_bad_flow_inputs_never_contact_provider(signing_key):
    fixture = ProviderFixture(signing_key)
    for bad in (None, "", "short", "!" * 43, "v" * 129):
        with pytest.raises(ProviderError, match="^invalid_state$"):
            await fixture.provider().start(STATE, NONCE, bad)
    for state in ({}, None, {"nonce": "", "code_verifier": VERIFIER}, {"nonce": NONCE, "code_verifier": "short"}):
        with pytest.raises(ProviderError, match="^invalid_state$"):
            await fixture.provider().finish(CODE, state)
    assert fixture.requests == []
