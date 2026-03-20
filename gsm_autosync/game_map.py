"""
Container name → DiscordGSM game info lookup table.

game_id strings verified against DiscordGSM's supported games list (v2.20).
CoreKeeper and Don't Starve Together are NOT supported by DiscordGSM and are
excluded. Use `!gsmsetup addgame` to manually map unsupported containers.
"""

GAME_MAP = {
    "satisfactory": {
        "game_id": "satisfactory",
        "query_port": 15777,
        "display_name": "Satisfactory",
    },
    "v-rising": {
        "game_id": "vrising",
        "query_port": 9877,
        "display_name": "V Rising",
    },
    "vrising": {
        "game_id": "vrising",
        "query_port": 9877,
        "display_name": "V Rising",
    },
    "valheim": {
        "game_id": "valheim",
        "query_port": 2457,
        "display_name": "Valheim",
    },
    "minecraftbasicserver": {
        "game_id": "minecraft",
        "query_port": 25565,
        "display_name": "Minecraft",
    },
    "binhex-minecraftserver": {
        "game_id": "minecraft",
        "query_port": 25565,
        "display_name": "Minecraft",
    },
    "minecraft-forge": {
        "game_id": "minecraft",
        "query_port": 25565,
        "display_name": "Minecraft (Forge)",
    },
    "killingfloor2": {
        "game_id": "killingfloor2",
        "query_port": 27015,
        "display_name": "Killing Floor 2",
    },
    "kf2": {
        "game_id": "killingfloor2",
        "query_port": 27015,
        "display_name": "Killing Floor 2",
    },
}


def get_game_info(container_name: str) -> dict | None:
    """Return game info for a container name, or None if not recognized.

    Matching is case-insensitive.
    """
    if not container_name:
        return None
    return GAME_MAP.get(container_name.lower())
