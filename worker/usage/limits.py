"""Free-tier limits and check_limit() helper for all API providers."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

FREE_TIER_LIMITS: dict[str, dict] = {
    "gemini-2.5-flash": {
        "cycle": "daily",
        "rpd": 250,
        "rpm": 10,
        "tpm": 250_000,
        "on_exceed": "block",
    },
    "gemini-2.0-flash": {
        "cycle": "daily",
        "rpd": 500,
        "rpm": 15,
        "tpm": 1_000_000,
        "on_exceed": "block",
        "sunset": "2026-06-01",
    },
    "pexels": {
        "cycle": "hourly+monthly",
        "rph": 200,
        "rpm_month": 20_000,
        "on_exceed": "block",
    },
    "imagen": {
        "cycle": "none",
        "on_exceed": "charge",
        "cost_per_unit": 0.02,
        "unit": "image",
    },
    "veo3": {
        "cycle": "none",
        "on_exceed": "charge",
        "cost_per_unit_fast": 0.15,
        "cost_per_unit_standard": 0.40,
        "unit": "second",
    },
    "google-tts": {
        "cycle": "monthly",
        "wavenet_chars": 1_000_000,
        "neural2_bytes": 1_000_000,
        "on_exceed": "charge",
        "cost_per_1m_chars": 16.0,
    },
    "edge-tts": {"cycle": "unlimited", "on_exceed": "none"},
    "wan": {"cycle": "unlimited", "on_exceed": "none"},
}


def next_daily_reset_utc() -> str:
    """Return ISO timestamp of next Pacific-midnight daily reset (UTC+8 offset)."""
    now = datetime.now(timezone.utc)
    # Pacific Standard Time = UTC-8; treat Pacific midnight as UTC 08:00
    reset_today = now.replace(hour=8, minute=0, second=0, microsecond=0)
    if now >= reset_today:
        reset_today += timedelta(days=1)
    return reset_today.strftime("%Y-%m-%dT%H:%M:%SZ")


def next_hourly_reset_utc() -> str:
    """Return ISO timestamp of the start of the next UTC hour."""
    now = datetime.now(timezone.utc)
    next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    return next_hour.strftime("%Y-%m-%dT%H:%M:%SZ")


def next_monthly_reset_utc() -> str:
    """Return ISO timestamp of the 1st of next month at 00:00 UTC."""
    now = datetime.now(timezone.utc)
    if now.month == 12:
        next_month = now.replace(year=now.year + 1, month=1, day=1,
                                  hour=0, minute=0, second=0, microsecond=0)
    else:
        next_month = now.replace(month=now.month + 1, day=1,
                                  hour=0, minute=0, second=0, microsecond=0)
    return next_month.strftime("%Y-%m-%dT%H:%M:%SZ")
