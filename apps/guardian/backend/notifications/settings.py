"""Operator-held Slack secret; never accept destinations from browser input."""
from dataclasses import dataclass, field
import hashlib
import json
import os
import re


@dataclass(frozen=True)
class NotificationSettings:
    webhook_url: str = field(default="", repr=False)
    destination_id: str = ""
    public_origin: str = ""
    state: str = "not_configured"


def load_notification_settings(identity_settings):
    if identity_settings.mode != "oidc":
        return NotificationSettings()
    raw = os.getenv("GUARDIAN_SLACK_WEBHOOK_URL", "")
    if not raw:
        return NotificationSettings()
    # Literal host and path grammar prevent URL-parser discrepancies, redirects,
    # credential/userinfo tricks, injected query parameters and arbitrary egress.
    if (len(raw) > 1024 or not re.fullmatch(
            r"https://hooks\.slack\.com/services/[A-Za-z0-9_-]{1,128}/[A-Za-z0-9_-]{1,128}/[A-Za-z0-9_-]{1,256}", raw)):
        return NotificationSettings(state="invalid")
    origin = identity_settings.ui_origin
    if not origin:
        return NotificationSettings(state="invalid")
    digest = hashlib.sha256(json.dumps([raw, origin], separators=(",", ":")).encode()).hexdigest()
    return NotificationSettings(raw, digest, origin, "configured")
