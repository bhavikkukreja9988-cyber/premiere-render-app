"""Centralized remote (Supabase) configuration.

This is the single place the app learns how to reach Supabase. Only *public*
client configuration lives here — the project URL and the publishable
(client-side) key. Never put a secret key, service-role key or database
password in this file or anywhere in the desktop app.

Values resolve in this order:
    1. Environment variables (SUPABASE_URL / SUPABASE_PUBLISHABLE_KEY) — handy
       during development and for pointing a build at a different project.
    2. The baked-in defaults below — what ships in the released app.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# Public project configuration for the "File Sender" Supabase project.
# The publishable key is explicitly safe to embed in client applications; RLS
# protects the data. See docs/SUPABASE_SETUP.md.
DEFAULT_SUPABASE_URL = "https://dyvhlaljbgpyywrofrbg.supabase.co"
DEFAULT_SUPABASE_PUBLISHABLE_KEY = "sb_publishable_CwBt3SKkspj5FTBmAQo9cw_4FJNOFqg"

# Usernames are mapped to synthetic emails so Supabase's email/password auth can
# be used while the user only ever types a username. This domain is never
# emailed; it just namespaces accounts. Email confirmation must be OFF in the
# Supabase dashboard for this to work (see docs/SUPABASE_SETUP.md).
USERNAME_EMAIL_DOMAIN = "filesender.local"

# Storage bucket names (created by the storage migration).
BUCKET_PROJECT_FILES = "project-files"
BUCKET_RENDER_RESULTS = "render-results"

# Heartbeat / presence timing (seconds).
HEARTBEAT_INTERVAL = 15.0
# A station not heard from for this long is considered offline.
STATION_OFFLINE_AFTER = 45.0


@dataclass(frozen=True)
class RemoteConfig:
    url: str
    publishable_key: str
    username_email_domain: str = USERNAME_EMAIL_DOMAIN
    bucket_project_files: str = BUCKET_PROJECT_FILES
    bucket_render_results: str = BUCKET_RENDER_RESULTS
    heartbeat_interval: float = HEARTBEAT_INTERVAL
    station_offline_after: float = STATION_OFFLINE_AFTER

    @property
    def configured(self) -> bool:
        return bool(self.url and self.publishable_key)


def load_remote_config() -> RemoteConfig:
    return RemoteConfig(
        url=os.environ.get("SUPABASE_URL", DEFAULT_SUPABASE_URL).rstrip("/"),
        publishable_key=os.environ.get("SUPABASE_PUBLISHABLE_KEY",
                                       DEFAULT_SUPABASE_PUBLISHABLE_KEY),
    )


def username_to_email(username: str, domain: str = USERNAME_EMAIL_DOMAIN) -> str:
    """Map a bare username to the synthetic email Supabase Auth stores.

    The user only ever sees the username; this keeps the mapping in one place so
    sign-up and sign-in always agree.
    """
    cleaned = (username or "").strip().lower()
    if not cleaned:
        raise ValueError("username must not be empty")
    if "@" in cleaned:
        # Already an email-like value; use as-is so power users aren't blocked.
        return cleaned
    safe = "".join(ch for ch in cleaned if ch.isalnum() or ch in "._-")
    if not safe:
        raise ValueError("username has no usable characters")
    return f"{safe}@{domain}"
