import sys, os, sqlite3, tempfile, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'gsm-autosync'))

import pytest
from db import (
    create_schema_if_missing,
    insert_server,
    delete_server_by_id,
    get_server_by_id,
    is_db_writable,
)

@pytest.fixture
def tmp_db(tmp_path):
    db_path = str(tmp_path / "servers.db")
    create_schema_if_missing(db_path)
    return db_path

def test_insert_returns_row_id(tmp_db):
    row_id = insert_server(tmp_db, {
        "guild_id": 111,
        "channel_id": 222,
        "game_id": "valheim",
        "address": "172.17.0.5",
        "query_port": 2457,
        "query_extra": "{}",
        "style_data": json.dumps({"fullname": "Valheim", "country": "CA"}),
    })
    assert isinstance(row_id, int)
    assert row_id > 0

def test_position_increments(tmp_db):
    id1 = insert_server(tmp_db, {
        "guild_id": 111, "channel_id": 222, "game_id": "valheim",
        "address": "172.17.0.5", "query_port": 2457,
        "query_extra": "{}", "style_data": "{}",
    })
    id2 = insert_server(tmp_db, {
        "guild_id": 111, "channel_id": 222, "game_id": "minecraft",
        "address": "172.17.0.6", "query_port": 25565,
        "query_extra": "{}", "style_data": "{}",
    })
    conn = sqlite3.connect(tmp_db)
    rows = conn.execute("SELECT position FROM servers ORDER BY id").fetchall()
    conn.close()
    assert rows[1][0] > rows[0][0]

def test_delete_by_id(tmp_db):
    row_id = insert_server(tmp_db, {
        "guild_id": 111, "channel_id": 222, "game_id": "valheim",
        "address": "172.17.0.5", "query_port": 2457,
        "query_extra": "{}", "style_data": "{}",
    })
    delete_server_by_id(tmp_db, row_id)
    assert get_server_by_id(tmp_db, row_id) is None

def test_delete_nonexistent_is_safe(tmp_db):
    # Should not raise
    delete_server_by_id(tmp_db, 99999)

def test_get_style_data_preserved(tmp_db):
    style = json.dumps({"fullname": "Valheim", "country": "CA", "description": "my server"})
    row_id = insert_server(tmp_db, {
        "guild_id": 111, "channel_id": 222, "game_id": "valheim",
        "address": "172.17.0.5", "query_port": 2457,
        "query_extra": "{}", "style_data": style,
    })
    row = get_server_by_id(tmp_db, row_id)
    assert row["style_data"] == style

def test_is_db_writable_true(tmp_db):
    assert is_db_writable(tmp_db) is True

def test_is_db_writable_false_missing_path():
    assert is_db_writable("/nonexistent/path/servers.db") is False
