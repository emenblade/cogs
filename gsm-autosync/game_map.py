"""
Container name → DiscordGSM game info lookup table.

game_id strings verified against DiscordGSM's supported games list.
query_port is the UDP query port (not the game port).
query_extra is passed directly to DiscordGSM — {} is correct for all listed games.
"""

GAME_MAP = {
    "satisfactory": {
        "game_id": "satisfactory",
        "query_port": 15777,
        "query_extra": {},
        "display_name": "Satisfactory",
    },
    "v-rising": {
        "game_id": "vrising",
        "query_port": 9877,
        "query_extra": {},
        "display_name": "V Rising",
    },
    "corekeeper": {
        "game_id": "corekeeper",
        "query_port": 27016,
        "query_extra": {},
        "display_name": "Core Keeper",
    },
    "dontstarvetogether": {
        "game_id": "dst",
        "query_port": 27016,
        "query_extra": {},
        "display_name": "Don't Starve Together",
    },
    "valheim": {
        "game_id": "valheim",
        "query_port": 2457,
        "query_extra": {},
        "display_name": "Valheim",
    },
    "minecraftbasicserver": {
        "game_id": "minecraft",
        "query_port": 25565,
        "query_extra": {},
        "display_name": "Minecraft",
    },
    "binhex-minecraftserver": {
        "game_id": "minecraft",
        "query_port": 25565,
        "query_extra": {},
        "display_name": "Minecraft",
    },
    "minecraft-forge": {
        "game_id": "minecraft",
        "query_port": 25565,
        "query_extra": {},
        "display_name": "Minecraft (Forge)",
    },
}


def get_game_info(container_name: str) -> dict | None:
    """Return game info for a container name, or None if not recognized.

    Matching is case-insensitive.
    """
    if not container_name:
        return None
    return GAME_MAP.get(container_name.lower())
