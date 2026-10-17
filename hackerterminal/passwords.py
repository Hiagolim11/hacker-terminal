"""SSH passwords kept in the system keyring (Secret Service: GNOME Keyring, KWallet).

The keyring encrypts them and unlocks with the user's login; Hacker
Terminal never writes a password to its own files. The ht-askpass helper
reads them back when ssh asks, so they are never typed into the terminal.
"""

from __future__ import annotations

import logging

LOGGER = logging.getLogger(__name__)
SCHEMA_NAME = "org.hackerterminal.HackerTerminal.SSH"

try:
    import gi

    gi.require_version("Secret", "1")
    from gi.repository import GLib, Secret
except (ImportError, ValueError):
    Secret = None

_schema = None


def available() -> bool:
    return Secret is not None


def schema():
    global _schema
    if _schema is None and Secret is not None:
        _schema = Secret.Schema.new(
            SCHEMA_NAME, Secret.SchemaFlags.NONE, {"connection": Secret.SchemaAttributeType.STRING}
        )
    return _schema


def lookup(identifier: str) -> str | None:
    if Secret is None:
        return None
    try:
        return Secret.password_lookup_sync(schema(), {"connection": identifier}, None)
    except GLib.Error as error:
        LOGGER.warning("chaveiro indisponível: %s", error.message)
        return None


def has_password(identifier: str) -> bool:
    return bool(lookup(identifier))


def store(identifier: str, label: str, password: str) -> bool:
    if Secret is None or not password:
        return False
    try:
        return Secret.password_store_sync(
            schema(), {"connection": identifier}, Secret.COLLECTION_DEFAULT,
            f"Hacker Terminal — SSH {label}", password, None,
        )
    except GLib.Error as error:
        LOGGER.warning("não foi possível guardar a senha no chaveiro: %s", error.message)
        return False


def forget(identifier: str) -> bool:
    if Secret is None:
        return False
    try:
        return Secret.password_clear_sync(schema(), {"connection": identifier}, None)
    except GLib.Error as error:
        LOGGER.warning("não foi possível apagar a senha do chaveiro: %s", error.message)
        return False
