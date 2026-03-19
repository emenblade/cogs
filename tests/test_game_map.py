import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'gsm-autosync'))

from game_map import get_game_info, GAME_MAP

def test_exact_match():
    info = get_game_info("Valheim")
    assert info is not None
    assert info["game_id"] == "valheim"
    assert info["query_port"] == 2457

def test_case_insensitive_match():
    assert get_game_info("valheim") is not None
    assert get_game_info("VALHEIM") is not None

def test_unknown_container_returns_none():
    assert get_game_info("nginx") is None
    assert get_game_info("plex") is None
    assert get_game_info("") is None

def test_minecraft_variants():
    assert get_game_info("MinecraftBasicServer")["game_id"] == "minecraft"
    assert get_game_info("binhex-minecraftserver")["game_id"] == "minecraft"
    assert get_game_info("Minecraft-forge")["game_id"] == "minecraft"

def test_dst_game_id():
    info = get_game_info("DontStarveTogether")
    assert info["game_id"] == "dst"

def test_all_entries_have_required_fields():
    required = {"game_id", "query_port", "query_extra", "display_name"}
    for name, info in GAME_MAP.items():
        assert required.issubset(info.keys()), f"{name} missing fields"

def test_query_extra_is_dict():
    for name, info in GAME_MAP.items():
        assert isinstance(info["query_extra"], dict), f"{name} query_extra must be dict"
