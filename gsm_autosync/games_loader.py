"""Loads and parses DiscordGSM's games.csv for dynamic game detection."""

import csv
import io
import logging
import re
import subprocess

log = logging.getLogger("red.gsm-autosync.games_loader")

# Common noise words to strip from container names before matching
_NOISE = re.compile(
    r"(dedicated|server|game|gameserver|binhex-|lsio-|linuxgsm-|my-|the-|-server|-game|-dedicated)",
    re.IGNORECASE,
)


def load_games_csv() -> dict[str, dict]:
    """Read games.csv from DiscordGSM container via docker exec.

    Returns {game_id: {name, query_port, protocol}} or {} on failure.
    """
    try:
        result = subprocess.run(
            ["docker", "exec", "DiscordGSM", "cat", "/usr/src/app/discordgsm/games.csv"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            log.warning("Could not read games.csv from DiscordGSM container: %s", result.stderr.strip())
            return {}

        games: dict[str, dict] = {}
        reader = csv.DictReader(io.StringIO(result.stdout))
        for row in reader:
            game_id = row.get("Id", "").strip()
            if not game_id:
                continue
            games[game_id] = {
                "name": row.get("Name", game_id).strip(),
                "query_port": _parse_query_port(row.get("Options", "")),
                "protocol": row.get("Protocol", "").strip(),
            }

        log.info("Loaded %d games from DiscordGSM games.csv", len(games))
        return games

    except FileNotFoundError:
        log.warning("docker not found — cannot load games.csv")
        return {}
    except subprocess.TimeoutExpired:
        log.warning("Timed out reading games.csv from DiscordGSM container")
        return {}
    except Exception as e:
        log.error("Failed to load games.csv: %s", e)
        return {}


def _parse_query_port(options: str) -> int | None:
    """Parse the default query port from an Options field value.

    Options examples:
      port=26900;port_query_offset=1  →  26901
      port_query=27015                →  27015
      port=2456                       →  2456
    """
    if not options:
        return None

    params: dict[str, str] = {}
    for part in options.split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            params[k.strip()] = v.strip()

    if "port_query" in params:
        try:
            return int(params["port_query"])
        except ValueError:
            pass

    if "port" in params:
        try:
            port = int(params["port"])
            offset = int(params.get("port_query_offset", 0))
            return port + offset
        except ValueError:
            pass

    return None


def fuzzy_match(
    container_name: str,
    exposed_ports: set[int],
    games: dict[str, dict],
) -> list[tuple[str, dict, float]]:
    """Match a container name + exposed ports against the DiscordGSM games dict.

    Scoring:
      +0.6  game_id found in container name
      +0.45 game_id found in cleaned name (noise stripped)
      +0.35 fraction of significant game name words found in container name
      +0.4  query port matches an exposed port

    Returns up to 3 candidates as (game_id, game_info, confidence), sorted desc.
    """
    name_lower = container_name.lower()
    name_clean = _NOISE.sub("", name_lower).strip("-_ ")

    results: list[tuple[str, dict, float]] = []

    for game_id, info in games.items():
        score = 0.0

        if game_id == name_lower:
            score += 1.0
        elif game_id in name_lower:
            score += 0.6
        elif game_id in name_clean:
            score += 0.45

        # Word overlap between game name and container name
        raw_name = re.sub(r"\s*\(\d{4}\)\s*", "", info["name"]).strip().lower()
        words = [w for w in re.split(r"\W+", raw_name) if len(w) >= 4]
        if words:
            hits = sum(1 for w in words if w in name_lower or w in name_clean)
            score += 0.35 * (hits / len(words))

        # Query port match
        qport = info.get("query_port")
        if qport and qport in exposed_ports:
            score += 0.4

        if score >= 0.2:
            results.append((game_id, info, min(score, 1.0)))

    results.sort(key=lambda x: x[2], reverse=True)
    return results[:3]
