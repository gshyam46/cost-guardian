"""Bounded OIDC code-flow adapter for a configured, trusted identity provider.

The caller owns one-use state consumption and browser binding. This module
returns only verified identity claims; provider tokens never leave ``finish``.
Authlib 1.8 uses HTTPX2; Guardian's telemetry HTTPX client is independent.
"""
from __future__ import annotations

import asyncio
import base64
from collections.abc import Mapping
from contextlib import asynccontextmanager
from contextvars import ContextVar
import hmac
import ipaddress
import logging
import math
import re
import time
from urllib.parse import urlsplit

from authlib.integrations.httpx_client import AsyncOAuth2Client
from authlib.oidc.core import CodeIDToken
import httpx2
from joserfc import jwt
from joserfc.jwk import KeySet


OPERATION_TIMEOUT_SECONDS = 15.0
REQUEST_TIMEOUT_SECONDS = 5.0
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_ID_TOKEN_LENGTH = 32768
CLOCK_SKEW_SECONDS = 30
_OPAQUE = re.compile(r"[A-Za-z0-9._~-]{20,256}\Z")
_VERIFIER = re.compile(r"[A-Za-z0-9._~-]{43,128}\Z")
_provider_io = ContextVar("guardian_oidc_provider_io", default=False)


class ProviderError(Exception):
    """Safe boundary error. Never retain a provider response or exception text."""

    CODES = frozenset({
        "invalid_configuration", "invalid_state", "provider_timeout",
        "provider_unavailable", "invalid_provider_metadata",
        "token_exchange_failed", "invalid_id_token",
    })

    def __init__(self, code):
        self.code = code if isinstance(code, str) and code in self.CODES else "provider_unavailable"
        super().__init__(self.code)


class _SafeProviderLogs(logging.Filter):
    def filter(self, record):
        if _provider_io.get():
            # HTTP reason phrases and DEBUG response headers are provider
            # controlled. Do not retain URLs, headers, exceptions or bodies.
            record.msg = "OIDC provider transport event"
            record.args = ()
            record.exc_info = None
            record.exc_text = None
            record.stack_info = None
        return True


_log_filter = _SafeProviderLogs()


def _install_log_filters():
    names = {
        "httpx2", "httpx", "httpcore", "httpcore2",
        "httpcore.connection", "httpcore.http11", "httpcore.http2",
        "httpcore.proxy", "httpcore.socks",
        "httpcore2.connection", "httpcore2.http11", "httpcore2.http2",
        "httpcore2.proxy", "httpcore2.socks",
    }
    names.update(name for name in list(logging.Logger.manager.loggerDict)
                 if name.startswith(("httpx.", "httpx2.", "httpcore.", "httpcore2.")))
    for name in names:
        logger = logging.getLogger(name)
        if _log_filter not in logger.filters:
            logger.addFilter(_log_filter)


def _text(value, maximum, *, ascii_only=False):
    return (isinstance(value, str) and 0 < len(value) <= maximum
            and not any(ord(char) < 32 or ord(char) == 127 for char in value)
            and (not ascii_only or value.isascii()))


def _url(value, allow_loopback_http, code):
    if (not _text(value, 2048) or any(char.isspace() for char in value)
            or any(char in value for char in ("\\", "?", "#"))):
        raise ProviderError(code)
    try:
        parsed = urlsplit(value)
        port = parsed.port
        if (not parsed.hostname or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or port == 0):
            raise ValueError()
        if parsed.scheme == "https":
            return value
        loopback = parsed.hostname == "localhost"
        try:
            loopback = loopback or ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError:
            pass
        if parsed.scheme == "http" and allow_loopback_http and loopback:
            return value
    except (TypeError, ValueError):
        pass
    raise ProviderError(code)


class _BoundedStream(httpx2.AsyncByteStream):
    def __init__(self, stream):
        self.stream = stream

    async def __aiter__(self):
        size = 0
        async for chunk in self.stream:
            size += len(chunk)
            if size > MAX_RESPONSE_BYTES:
                raise ProviderError("provider_unavailable")
            yield chunk

    async def aclose(self):
        await self.stream.aclose()


class _BoundedTransport(httpx2.AsyncBaseTransport):
    def __init__(self, transport):
        self.transport = transport

    async def handle_async_request(self, request):
        response = await self.transport.handle_async_request(request)
        try:
            # Count raw representation bytes before any HTTPX decoder can
            # expand them. This deliberately requires identity wire encoding.
            if response.headers.get("content-encoding", "identity").lower().strip() != "identity":
                raise ProviderError("provider_unavailable")
            length = response.headers.get("content-length")
            if length is not None and (not length.isdigit() or int(length) > MAX_RESPONSE_BYTES):
                raise ProviderError("provider_unavailable")
            response.stream = _BoundedStream(response.stream)
            return response
        except BaseException:
            await response.aclose()
            raise

    async def aclose(self):
        await self.transport.aclose()


class OIDCProvider:
    def __init__(self, issuer, client_id, client_secret, redirect_uri,
                 allow_loopback_http=False, transport=None):
        if type(allow_loopback_http) is not bool:
            raise ProviderError("invalid_configuration")
        self.issuer = _url(issuer, allow_loopback_http, "invalid_configuration")
        self.redirect_uri = _url(redirect_uri, allow_loopback_http, "invalid_configuration")
        if not _text(client_id, 1024) or not _text(client_secret, 8192):
            raise ProviderError("invalid_configuration")
        self.client_id = client_id
        self._client_secret = client_secret
        self._allow_loopback_http = allow_loopback_http
        self._transport = transport

    @asynccontextmanager
    async def _client(self):
        _install_log_filters()
        context = _provider_io.set(True)
        try:
            async with asyncio.timeout(OPERATION_TIMEOUT_SECONDS):
                transport = self._transport or httpx2.AsyncHTTPTransport(retries=0, trust_env=False)
                async with AsyncOAuth2Client(
                    self.client_id, self._client_secret, redirect_uri=self.redirect_uri,
                    scope="openid profile", code_challenge_method="S256",
                    token_endpoint_auth_method="client_secret_basic",
                    transport=_BoundedTransport(transport), trust_env=False,
                    follow_redirects=False, timeout=REQUEST_TIMEOUT_SECONDS,
                    headers={"Accept": "application/json", "Accept-Encoding": "identity"},
                ) as client:
                    yield client
        except ProviderError:
            raise
        except (TimeoutError, httpx2.TimeoutException):
            raise ProviderError("provider_timeout") from None
        except Exception:
            raise ProviderError("provider_unavailable") from None
        finally:
            _provider_io.reset(context)

    async def _json(self, client, url):
        response = await client.request("GET", url, withhold_token=True)
        if response.status_code != 200:
            raise ProviderError("provider_unavailable")
        try:
            value = response.json()
        except (TypeError, ValueError):
            raise ProviderError("invalid_provider_metadata") from None
        if not isinstance(value, dict):
            raise ProviderError("invalid_provider_metadata")
        return value

    async def _metadata(self, client):
        value = await self._json(client, self.issuer.rstrip("/") + "/.well-known/openid-configuration")
        if value.get("issuer") != self.issuer:
            raise ProviderError("invalid_provider_metadata")
        for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
            _url(value.get(key), self._allow_loopback_http, "invalid_provider_metadata")
        for key, required, default in (
            ("response_types_supported", "code", None),
            ("id_token_signing_alg_values_supported", "RS256", None),
            ("token_endpoint_auth_methods_supported", "client_secret_basic", ["client_secret_basic"]),
            ("code_challenge_methods_supported", "S256", ["S256"]),
        ):
            supported = value.get(key, default)
            if not isinstance(supported, list) or required not in supported:
                raise ProviderError("invalid_provider_metadata")
        return value

    async def start(self, state, nonce, verifier):
        if (not isinstance(state, str) or not _OPAQUE.fullmatch(state)
                or not isinstance(nonce, str) or not _OPAQUE.fullmatch(nonce)
                or not isinstance(verifier, str) or not _VERIFIER.fullmatch(verifier)):
            raise ProviderError("invalid_state")
        async with self._client() as client:
            metadata = await self._metadata(client)
            authorization_url, returned_state = client.create_authorization_url(
                metadata["authorization_endpoint"], state=state, nonce=nonce,
                code_verifier=verifier, response_type="code", response_mode="query",
            )
            if returned_state != state:
                raise ProviderError("invalid_state")
            return authorization_url

    async def finish(self, code, state_data):
        if (not _text(code, 4096, ascii_only=True) or not isinstance(state_data, Mapping)
                or not isinstance(state_data.get("nonce"), str)
                or not _OPAQUE.fullmatch(state_data["nonce"])
                or not isinstance(state_data.get("code_verifier"), str)
                or not _VERIFIER.fullmatch(state_data["code_verifier"])):
            raise ProviderError("invalid_state")
        async with self._client() as client:
            metadata = await self._metadata(client)

            def check_token_response(response):
                if response.status_code != 200:
                    safe_code = "token_exchange_failed" if 400 <= response.status_code < 500 and response.status_code != 429 else "provider_unavailable"
                    raise ProviderError(safe_code)
                return response

            client.register_compliance_hook("access_token_response", check_token_response)
            try:
                token = await client.fetch_token(
                    metadata["token_endpoint"], grant_type="authorization_code",
                    code=code, code_verifier=state_data["code_verifier"],
                    redirect_uri=self.redirect_uri,
                )
            except (ProviderError, httpx2.TimeoutException):
                raise
            except httpx2.HTTPError:
                raise ProviderError("provider_unavailable") from None
            except Exception:
                raise ProviderError("token_exchange_failed") from None
            if (not isinstance(token, Mapping) or not _text(token.get("id_token"), MAX_ID_TOKEN_LENGTH, ascii_only=True)
                    or not _text(token.get("access_token"), 8192, ascii_only=True)
                    or not isinstance(token.get("token_type"), str) or token["token_type"].lower() != "bearer"):
                raise ProviderError("invalid_id_token")
            keys = await self._json(client, metadata["jwks_uri"])
            return self._identity(token, keys, state_data["nonce"])

    def _identity(self, token, jwks, nonce):
        try:
            keys = jwks.get("keys")
            if not isinstance(keys, list) or not 1 <= len(keys) <= 32:
                raise ValueError()
            accepted = []
            identifiers = set()
            for key in keys:
                if not isinstance(key, dict):
                    raise ValueError()
                if key.get("kty") != "RSA" or key.get("use", "sig") != "sig" or key.get("alg", "RS256") != "RS256":
                    continue
                if "key_ops" in key and (not isinstance(key["key_ops"], list) or "verify" not in key["key_ops"]):
                    continue
                if (not _text(key.get("n"), 1400, ascii_only=True) or not _text(key.get("e"), 16, ascii_only=True)
                        or any(part in key for part in ("d", "p", "q", "dp", "dq", "qi"))):
                    raise ValueError()
                modulus = key["n"]
                if not re.fullmatch(r"[A-Za-z0-9_-]+", modulus):
                    raise ValueError()
                modulus_bits = int.from_bytes(base64.urlsafe_b64decode(modulus + "=" * (-len(modulus) % 4)), "big").bit_length()
                if not 2048 <= modulus_bits <= 8192:
                    raise ValueError()
                kid = key.get("kid")
                if kid is not None and not _text(kid, 256):
                    raise ValueError()
                if kid in identifiers:
                    raise ValueError()
                identifiers.add(kid)
                accepted.append(key)
            if not accepted:
                raise ValueError()
            verified = jwt.decode(token["id_token"], KeySet.import_key_set({"keys": accepted}), algorithms=["RS256"])
            claims = verified.claims
            if not isinstance(claims, dict) or not _text(claims.get("sub"), 255, ascii_only=True):
                raise ValueError()
            audiences = claims.get("aud")
            if isinstance(audiences, str):
                audiences = [audiences]
            if (not isinstance(audiences, list) or not 1 <= len(audiences) <= 20
                    or not all(_text(value, 1024) for value in audiences)
                    or self.client_id not in audiences):
                raise ValueError()
            if "azp" in claims and claims["azp"] != self.client_id:
                raise ValueError()
            if len(audiences) > 1 and claims.get("azp") != self.client_id:
                raise ValueError()
            for name in ("exp", "iat", "nbf"):
                if name == "nbf" and name not in claims:
                    continue
                value = claims.get(name)
                if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 253402300799:
                    raise ValueError()
            if claims["exp"] <= claims["iat"] or claims["exp"] <= time.time() - CLOCK_SKEW_SECONDS:
                raise ValueError()
            if not isinstance(claims.get("nonce"), str) or not hmac.compare_digest(claims["nonce"], nonce):
                raise ValueError()
            if "at_hash" in claims and not _text(claims["at_hash"], 256, ascii_only=True):
                raise ValueError()
            # Use the public verifier directly. Authlib's generic OIDC mixin
            # disables nonce checking for nonce_supported:false; we never do.
            validated = CodeIDToken(claims, verified.header, {
                "iss": {"essential": True, "value": self.issuer},
                "aud": {"essential": True, "value": self.client_id},
                "sub": {"essential": True}, "nonce": {"essential": True, "value": nonce},
            }, {"client_id": self.client_id, "nonce": nonce, "access_token": token["access_token"]})
            validated.validate(leeway=CLOCK_SKEW_SECONDS)
            name = claims.get("name")
            name = name.strip() if _text(name, 200) and name.strip() else None
            return {"issuer": self.issuer, "subject": claims["sub"], "name": name}
        except Exception:
            raise ProviderError("invalid_id_token") from None
