"""Fail-closed identity configuration; no discovery or secret values in errors."""
from dataclasses import dataclass, field
import ipaddress
import json
import os
import re
from urllib.parse import urlsplit

from .errors import IdentityError


@dataclass(frozen=True)
class Member:
    subject: str
    role: str
    name: str


@dataclass(frozen=True)
class Settings:
    mode: str = "api_key"
    issuer: str = ""
    client_id: str = ""
    client_secret: str = field(default="", repr=False)
    public_url: str = ""
    ui_origin: str = ""
    organization_id: str = ""
    project_id: str = ""
    environment: str = ""
    project_name: str = ""
    connection_id: str = "primary"
    members: dict = field(default_factory=dict, repr=False)
    allow_loopback_http: bool = False

    @property
    def binding(self):
        return {key: getattr(self, key) for key in (
            "organization_id", "project_id", "environment", "connection_id", "issuer", "client_id")}

    @property
    def secure_cookies(self):
        return not self.allow_loopback_http

    @property
    def session_cookie(self):
        return "__Host-guardian_session" if self.secure_cookies else "guardian_session"

    @property
    def login_cookie(self):
        return "__Host-guardian_login" if self.secure_cookies else "guardian_login"

    @property
    def redirect_uri(self):
        return self.public_url + "/api/guardian/auth/callback"


def _text(value, limit=255):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= limit and all(ord(c) >= 32 and ord(c) != 127 for c in value)


def _loopback(host):
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _url(value, local, *, origin=False):
    if not _text(value, 2048) or any(c.isspace() for c in value) or any(c in value for c in "\\?#"):
        raise ValueError()
    parsed = urlsplit(value)
    if (not parsed.hostname or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or parsed.port == 0):
        raise ValueError()
    if local:
        if not _loopback(parsed.hostname) or parsed.scheme not in {"http", "https"}:
            raise ValueError()
    elif parsed.scheme != "https":
        raise ValueError()
    if origin and parsed.path not in ("", "/"):
        raise ValueError()
    # Issuer comparison is exact, including an issuer's meaningful trailing slash.
    if not origin:
        return value
    host = parsed.hostname
    if not host.isascii() or "%" in host or parsed.netloc.endswith(":"):
        raise ValueError()
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        # Support ordinary ASCII DNS names (including explicit punycode), not
        # browser-specific integer/hex/short IPv4 forms or scoped/IPvFuture IPs.
        labels = host.split(".")
        if (parsed.netloc.startswith("[") or len(host) > 253
                or not all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels)
                or re.fullmatch(r"(?:[0-9]+|0x[0-9a-f]+)", labels[-1])):
            raise ValueError()
    else:
        host = f"[{address.compressed}]" if address.version == 6 else str(address)
    scheme = parsed.scheme.lower()
    port = parsed.port
    suffix = "" if port is None or (scheme, port) in {("https", 443), ("http", 80)} else f":{port}"
    return f"{scheme}://{host}{suffix}"


def load_settings():
    mode = os.getenv("GUARDIAN_AUTH_MODE", "api_key")
    if mode == "api_key":
        return Settings()
    if mode != "oidc":
        raise IdentityError(503, "invalid_configuration")
    try:
        local_value = os.getenv("GUARDIAN_ALLOW_INSECURE_LOCAL_AUTH", "false")
        if local_value not in {"true", "false"}:
            raise ValueError()
        local = local_value == "true"
        issuer = _url(os.environ["GUARDIAN_OIDC_ISSUER"], local)
        public = _url(os.environ["GUARDIAN_PUBLIC_URL"], local, origin=True)
        ui = _url(os.getenv("GUARDIAN_UI_ORIGIN", public), local, origin=True)
        if not local and public != ui:
            raise ValueError()
        values = {key: os.environ[env] for key, env in (
            ("client_id", "GUARDIAN_OIDC_CLIENT_ID"), ("client_secret", "GUARDIAN_OIDC_CLIENT_SECRET"),
            ("organization_id", "GUARDIAN_ORGANIZATION_ID"), ("project_id", "GUARDIAN_PROJECT_ID"),
            ("environment", "GUARDIAN_ENVIRONMENT"), ("project_name", "GUARDIAN_PROJECT_NAME"))}
        values["connection_id"] = os.getenv("GUARDIAN_CONNECTION_ID", "primary")
        if not all(_text(v, 4096 if k == "client_secret" else 120) for k, v in values.items()):
            raise ValueError()
        for key in ("organization_id", "project_id", "environment", "connection_id"):
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}", values[key]):
                raise ValueError()
        raw = os.environ["GUARDIAN_OIDC_MEMBERS_JSON"]
        if len(raw) > 65536:
            raise ValueError()
        entries = json.loads(raw)
        if not isinstance(entries, list) or not 1 <= len(entries) <= 100:
            raise ValueError()
        members = {}
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {"subject", "name", "role"}:
                raise ValueError()
            subject, name, role = entry["subject"], entry["name"], entry["role"]
            if not _text(subject) or not subject.isascii() or not _text(name, 120) or role not in ("owner", "operator", "viewer") or subject in members:
                raise ValueError()
            members[subject] = Member(subject, role, name)
        if not any(member.role == "owner" for member in members.values()):
            raise ValueError()
        return Settings(mode=mode, issuer=issuer, public_url=public, ui_origin=ui,
                        allow_loopback_http=local, members=members, **values)
    except (KeyError, TypeError, ValueError, RecursionError):
        raise IdentityError(503, "invalid_configuration") from None
