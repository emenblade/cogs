"""SQLite helpers for interacting with DiscordGSM's servers.db.

All functions open and close their own connection to stay safe under
concurrent access with DiscordGSM. timeout=10 handles SQLITE_BUSY.
"""

import sqlite3
import json
import os
import logging

log = logging.getLogger("red.gsm-autosync.db")

_TIMEOUT = 10  # seconds to wait on SQLITE_BUSY


def create_schema_if_missing(db_path: str) -> None:
    """Create the servers table if it doesn't exist.

    Safe to call on an existing DiscordGSM database — uses IF NOT EXISTS.
    """
    conn = None
    try:
        conn = sqlite3.connect(db_path, timeout=_TIMEOUT)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS servers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                position INT NOT NULL DEFAULT 0,
                guild_id BIGINT NOT NULL,
                channel_id BIGINT NOT NULL,
                message_id BIGINT,
                game_id TEXT NOT NULL,
                address TEXT NOT NULL,
                query_port INT NOT NULL,
                query_extra TEXT NOT NULL DEFAULT '{}',
                status INT NOT NULL DEFAULT 1,
                result TEXT NOT NULL DEFAULT '{}',
                style_id TEXT NOT NULL DEFAULT 'Large',
                style_data TEXT NOT NULL DEFAULT '{}'
            )
        """)
        conn.commit()
    except sqlite3.OperationalError as e:
        log.error("Failed to create schema: %s", e)
    finally:
        if conn:
            conn.close()


def insert_server(db_path: str, data: dict) -> int | None:
    """Insert a server row and return the new row id.

    data keys: guild_id, channel_id, game_id, address, query_port,
               query_extra (str), style_data (str JSON)
    Returns the new row id, or None on failure.
    """
    conn = None
    try:
        conn = sqlite3.connect(db_path, timeout=_TIMEOUT)
        conn.row_factory = sqlite3.Row
        with conn:
            cur = conn.execute("SELECT MAX(position) FROM servers")
            max_pos = cur.fetchone()[0]
            position = (max_pos + 1) if max_pos is not None else 0

            cur = conn.execute("""
                INSERT INTO servers
                    (position, guild_id, channel_id, message_id, game_id,
                     address, query_port, query_extra, status, result,
                     style_id, style_data)
                VALUES (?, ?, ?, NULL, ?, ?, ?, ?, 0, '{"raw": {}}', 'Large', ?)
            """, (
                position,
                data["guild_id"],
                data["channel_id"],
                data["game_id"],
                data["address"],
                data["query_port"],
                data["query_extra"],
                data["style_data"],
            ))
            return cur.lastrowid
    except sqlite3.OperationalError as e:
        log.error("Failed to insert server row: %s", e)
        return None
    finally:
        if conn:
            conn.close()


def delete_server_by_id(db_path: str, row_id: int) -> None:
    """Delete a server row by its primary key id."""
    conn = None
    try:
        conn = sqlite3.connect(db_path, timeout=_TIMEOUT)
        with conn:
            conn.execute("DELETE FROM servers WHERE id = ?", (row_id,))
    except sqlite3.OperationalError as e:
        log.error("Failed to delete server row id=%s: %s", row_id, e)
    finally:
        if conn:
            conn.close()


def get_server_by_id(db_path: str, row_id: int) -> dict | None:
    """Return a server row as a dict, or None if not found."""
    conn = None
    try:
        conn = sqlite3.connect(db_path, timeout=_TIMEOUT)
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT * FROM servers WHERE id = ?", (row_id,))
        row = cur.fetchone()
        return dict(row) if row else None
    except sqlite3.OperationalError as e:
        log.error("Failed to get server row id=%s: %s", row_id, e)
        return None
    finally:
        if conn:
            conn.close()


def is_db_writable(db_path: str) -> bool:
    """Return True if the DB file exists and is writable."""
    try:
        if not os.path.exists(db_path):
            # Try creating it (new setup)
            conn = sqlite3.connect(db_path, timeout=2)
            conn.close()
            return True
        return os.access(db_path, os.W_OK)
    except Exception:
        return False
