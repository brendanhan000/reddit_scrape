"""Configuration loading from environment / .env.

Credentials are NEVER hardcoded. ``load_env`` pulls a local ``.env`` into the
process environment, then typed config objects are built from it with clear
errors when something required is missing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class RedditCredentials:
    """OAuth credentials for a Reddit 'script' app."""

    client_id: str
    client_secret: str
    user_agent: str


@dataclass(frozen=True)
class MySQLConfig:
    """Connection settings for the optional MySQL sink."""

    host: str
    port: int
    user: str
    password: str
    database: str
    connect_timeout: int = 10


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or malformed."""


def load_env(dotenv_path: str | None = None) -> None:
    """Load a .env file into ``os.environ`` (no-op if python-dotenv absent)."""
    try:
        from dotenv import load_dotenv
    except ImportError:  # dotenv is optional; env may be set externally
        return
    if dotenv_path:
        load_dotenv(dotenv_path)
    else:
        load_dotenv()


def _get(name: str, default: str | None = None) -> str:
    return (os.environ.get(name) or (default or "")).strip()


def load_reddit_credentials() -> RedditCredentials:
    """Build :class:`RedditCredentials` from ``REDDIT_*`` env vars."""
    client_id = _get("REDDIT_CLIENT_ID")
    client_secret = _get("REDDIT_CLIENT_SECRET")
    user_agent = _get("REDDIT_USER_AGENT")

    missing = [
        name
        for name, value in (
            ("REDDIT_CLIENT_ID", client_id),
            ("REDDIT_CLIENT_SECRET", client_secret),
            ("REDDIT_USER_AGENT", user_agent),
        )
        if not value
    ]
    if missing:
        raise ConfigError(
            "Missing required Reddit env vars: "
            + ", ".join(missing)
            + ". Copy .env.example to .env and fill them in (see README)."
        )
    return RedditCredentials(client_id, client_secret, user_agent)


def load_mysql_config() -> MySQLConfig:
    """Build :class:`MySQLConfig` from ``MYSQL_*`` env vars."""
    host = _get("MYSQL_HOST")
    user = _get("MYSQL_USER")
    database = _get("MYSQL_DATABASE")
    password = os.environ.get("MYSQL_PASSWORD", "")  # may legitimately be empty

    missing = [
        name
        for name, value in (
            ("MYSQL_HOST", host),
            ("MYSQL_USER", user),
            ("MYSQL_DATABASE", database),
        )
        if not value
    ]
    if missing:
        raise ConfigError(
            "Missing required MySQL env vars: "
            + ", ".join(missing)
            + ". These are only needed with --mysql."
        )

    try:
        port = int(_get("MYSQL_PORT", "3306"))
    except ValueError as exc:
        raise ConfigError(f"MYSQL_PORT must be an integer: {exc}") from exc
    try:
        connect_timeout = int(_get("MYSQL_CONNECT_TIMEOUT", "10"))
    except ValueError:
        connect_timeout = 10

    return MySQLConfig(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        connect_timeout=connect_timeout,
    )
