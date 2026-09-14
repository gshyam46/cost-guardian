"""Allowlisted configuration; diagnostics never include values or credentials."""
from dataclasses import dataclass, field
import os
import re

from ._vendor.guardian_capture import target

_TOKEN = re.compile(r"cg_ingest_[0-9a-f]{32}_[A-Za-z0-9_-]{43}\Z")
_LABEL = re.compile(r"[A-Za-z0-9_.:/-]{1,120}\Z")


class ConfigurationError(ValueError):
    """Fixed diagnostic code, without customer configuration in the message."""


def _setting(env, name, default=""):
    modern, old = "SILLAGE_" + name, "GUARDIAN_" + name
    current, previous = env.get(modern), env.get(old)
    if current is not None and previous is not None and current != previous:
        raise ConfigurationError("conflicting_" + name.lower())
    return current if current is not None else previous if previous is not None else default


@dataclass(frozen=True)
class Configuration:
    origin: str
    token: str = field(repr=False)
    service_name: str = "python-app"
    allow_local: bool = False

    def __post_init__(self):
        try:
            if type(self.origin) is not str or type(self.allow_local) is not bool:
                raise ValueError()
            target(self.origin, self.allow_local)
        except Exception:
            raise ConfigurationError("invalid_collector_origin") from None
        if type(self.token) is not str or not _TOKEN.fullmatch(self.token):
            raise ConfigurationError("invalid_ingestion_key")
        if type(self.service_name) is not str or not _LABEL.fullmatch(self.service_name):
            raise ConfigurationError("invalid_service_name")

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        local = _setting(env, "ALLOW_LOCAL", "false")
        if local not in ("true", "false"):
            raise ConfigurationError("invalid_allow_local")
        return cls(_setting(env, "URL"), _setting(env, "INGEST_KEY"),
                   _setting(env, "SERVICE_NAME", "python-app"), local == "true")

