"""Safe source errors shared by version-specific adapters."""


class SourceReadError(Exception):
    """Contains an allowlisted code, never provider response bodies or secrets."""

    CODES = {
        "not_configured", "invalid_configuration", "read_timeout", "upstream_error",
        "authentication_failed", "rate_limited", "invalid_response", "invalid_query",
        "not_found", "unsupported_api", "response_too_large",
    }

    def __init__(self, code: str):
        self.code = code if code in self.CODES else "upstream_error"
        super().__init__(self.code)
