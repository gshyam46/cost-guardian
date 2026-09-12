"""Validate explicit packaged configuration before importing application state."""
from dataclasses import dataclass, field
import ipaddress
import os
from pathlib import Path
import re
import stat
import warnings
from urllib.parse import parse_qsl, unquote, urlsplit

from .errors import DeploymentError

SECRET_LIMITS = {"MONGO_URL": 8192, "GUARDIAN_OIDC_CLIENT_SECRET": 4096,
                 "GUARDIAN_OIDC_MEMBERS_JSON": 65536, "GUARDIAN_SLACK_WEBHOOK_URL": 1024}


def prepare_environment():
    """Resolve only documented file secrets, atomically, before config imports."""
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    updates, consumed = {}, []
    try:
        for key, maximum in SECRET_LIMITS.items():
            filename_key = key + "_FILE"
            if filename_key not in os.environ:
                continue
            if key in os.environ or not os.environ[filename_key]:
                raise ValueError()
            path = Path(os.environ[filename_key])
            if not stat.S_ISREG(path.stat().st_mode):
                raise ValueError()
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0))
            with os.fdopen(descriptor, "rb") as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise ValueError()
                raw = stream.read(maximum + 3)
            if len(raw) > maximum + 2:
                raise ValueError()
            value = raw.decode("utf-8")
            if value.endswith("\r\n"):
                value = value[:-2]
            elif value.endswith("\n"):
                value = value[:-1]
            if not value or len(value.encode("utf-8")) > maximum or "\x00" in value:
                raise ValueError()
            updates[key] = value
            consumed.append(filename_key)
        os.environ.update(updates)
        # Subsequent readiness reads use this process's frozen secret values.
        for key in consumed:
            del os.environ[key]
    except (OSError, ValueError, UnicodeError):
        raise DeploymentError("invalid_secret_configuration") from None


def _loopback(host):
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def validate_mongo_url(value, *, local=False):
    """Syntax/security validation only: SRV names are never resolved by check."""
    try:
        if not isinstance(value, str) or not 1 <= len(value) <= 8192 or any(ord(c) <= 32 for c in value):
            raise ValueError()
        parsed = urlsplit(value)
        if parsed.scheme not in {"mongodb", "mongodb+srv"} or parsed.fragment or not parsed.netloc:
            raise ValueError()
        authority = parsed.netloc
        if authority.count("@") > 1:
            raise ValueError()
        credentials, hosts = authority.rsplit("@", 1) if "@" in authority else (None, authority)
        if not local:
            if credentials is None or ":" not in credentials:
                raise ValueError()
            username, password = credentials.split(":", 1)
            if not unquote(username) or not unquote(password):
                raise ValueError()
        entries = hosts.split(",")
        if not 1 <= len(entries) <= 20 or parsed.scheme == "mongodb+srv" and len(entries) != 1:
            raise ValueError()
        for entry in entries:
            endpoint = urlsplit("//" + entry)
            host = endpoint.hostname
            if not host or endpoint.path or endpoint.username is not None or endpoint.port == 0:
                raise ValueError()
            if local and not _loopback(host):
                raise ValueError()
            if parsed.scheme == "mongodb+srv" and (endpoint.port is not None or local):
                raise ValueError()
        pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True, max_num_fields=30)
        options = {key.lower(): value.lower() for key, value in pairs}
        if len(options) != len(pairs):
            raise ValueError()
        if parsed.query:
            # MongoClient otherwise parses with warn=True and can print an
            # operator-controlled invalid option. This helper performs no DNS.
            from pymongo.uri_parser import split_options
            with warnings.catch_warnings():
                warnings.simplefilter("error")
                split_options(parsed.query, validate=True, warn=False, normalize=True)
        if options.get("loadbalanced") == "true":
            raise ValueError()
        if not local:
            for key in ("tlsinsecure", "tlsallowinvalidcertificates", "tlsallowinvalidhostnames"):
                if options.get(key, "false") != "false":
                    raise ValueError()
            if any(options.get(key) not in (None, "true") for key in ("tls", "ssl")):
                raise ValueError()
            if parsed.scheme == "mongodb" and options.get("tls", options.get("ssl")) != "true":
                raise ValueError()
        return value
    except Exception:
        raise DeploymentError("invalid_mongo_configuration") from None


@dataclass(frozen=True)
class Configuration:
    identity: object = field(repr=False)
    mongo_url: str = field(repr=False)
    database_name: str
    static_dir: Path
    poll_interval: int
    bind_host: str = "127.0.0.1"
    port: int = 8001
    trusted_proxy_ips: tuple = ()


def load_configuration():
    """No database/client construction, network I/O or provider discovery."""
    from identity.settings import load_settings
    from notifications.settings import load_notification_settings
    from .static import validate_static_directory

    try:
        if os.getenv("GUARDIAN_AUTH_MODE") != "oidc" or os.getenv("GUARDIAN_CAPTURE_MODE") != "direct":
            raise ValueError()
        required = ("MONGO_URL", "GUARDIAN_DB_NAME", "GUARDIAN_CONNECTION_ID", "GUARDIAN_STATIC_DIR")
        if any(not os.environ.get(key) for key in required):
            raise ValueError()
        identity = load_settings()
        mongo_url = validate_mongo_url(os.environ["MONGO_URL"], local=identity.allow_loopback_http)
        database_name = os.environ["GUARDIAN_DB_NAME"]
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,62}", database_name) or database_name.lower() in {"admin", "local", "config"}:
            raise ValueError()
        polling = os.getenv("GUARDIAN_POLL_INTERVAL_SECONDS", "60")
        port = os.getenv("GUARDIAN_PORT", "8001")
        if not re.fullmatch(r"[0-9]{1,3}", polling) or not 1 <= int(polling) <= 300:
            raise ValueError()
        if not re.fullmatch(r"[0-9]{1,5}", port) or not 1 <= int(port) <= 65535:
            raise ValueError()
        host = os.getenv("GUARDIAN_BIND_HOST", "127.0.0.1")
        ipaddress.ip_address(host)
        proxies = os.getenv("GUARDIAN_TRUSTED_PROXY_IPS", "")
        trusted = tuple(proxies.split(",")) if proxies else ()
        if len(trusted) > 16:
            raise ValueError()
        for address in trusted:
            ipaddress.ip_address(address)
        directory = validate_static_directory(Path(os.environ["GUARDIAN_STATIC_DIR"])).directory
        if load_notification_settings(identity).state == "invalid":
            raise ValueError()
        return Configuration(identity, mongo_url, database_name, directory, int(polling), host, int(port), trusted)
    except DeploymentError:
        raise
    except Exception:
        raise DeploymentError("invalid_deployment_configuration") from None
