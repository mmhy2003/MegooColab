"""The named limits: their size comes from settings (`RATE_LIMIT_*`), their window is fixed here."""

from dataclasses import dataclass

from app.core.config import get_settings

MINUTE = 60
QUARTER_HOUR = 15 * MINUTE
HOUR = 60 * MINUTE


@dataclass(frozen=True)
class Limit:
    name: str
    max: int
    window: int  # seconds


# limit name -> (settings field, window)
_LIMITS: dict[str, tuple[str, int]] = {
    "login_ip": ("rate_limit_login_per_ip", QUARTER_HOUR),
    "totp_account": ("rate_limit_totp_per_account", QUARTER_HOUR),
    "forgot_email": ("rate_limit_forgot_per_email", HOUR),
    "forgot_ip": ("rate_limit_forgot_per_ip", HOUR),
    "reset_ip": ("rate_limit_token_pages_per_ip", HOUR),
    "invite_ip": ("rate_limit_token_pages_per_ip", HOUR),
    "setup_ip": ("rate_limit_token_pages_per_ip", HOUR),
    "change_password_user": ("rate_limit_change_password_per_user", QUARTER_HOUR),
    "api_user": ("rate_limit_api_per_user", MINUTE),
    "api_ip": ("rate_limit_api_per_ip", MINUTE),
    "ai_user": ("rate_limit_ai_per_user", MINUTE),
    "webhook_connection": ("rate_limit_webhook_per_connection", MINUTE),
    "ws_connect": ("rate_limit_ws_connect", MINUTE),
}


def get(name: str) -> Limit:
    field, window = _LIMITS[name]
    return Limit(name, getattr(get_settings(), field), window)
