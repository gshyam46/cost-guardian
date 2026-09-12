"""Prevent authorization codes and state in callback query access logs."""
import logging
import re
from urllib.parse import unquote

_LOG_TOKEN = re.compile(r"\S+")


def _redact(value):
    # Starlette redirects a trailing slash; HTTP clients may retain encoded paths.
    decoded = unquote(value)
    if "/api/guardian/auth/callback" in decoded and "?" in value:
        return value.split("?", 1)[0]
    return value


class CallbackQueryFilter(logging.Filter):
    def filter(self, record):
        if record.name == "uvicorn.access" and isinstance(record.args, tuple) and len(record.args) == 5:
            args = list(record.args)
            if isinstance(args[2], str):
                args[2] = _redact(args[2])
            record.args = tuple(args)
        else:
            message = record.getMessage()
            sanitized = _LOG_TOKEN.sub(lambda match: _redact(match.group()), message)
            if sanitized != message:
                record.msg = sanitized
                record.args = ()
        return True


def install_callback_log_filter():
    for name in ("uvicorn.access", "httpx", "httpx2"):
        logger = logging.getLogger(name)
        if not any(isinstance(item, CallbackQueryFilter) for item in logger.filters):
            logger.addFilter(CallbackQueryFilter())
