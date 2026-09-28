"""Constants, environment helpers, and stderr logging."""
from __future__ import annotations

import logging
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote, urlparse

IB_ORIGIN = "https://infinitebacklog.net"
WINDOWS_PC_PLATFORM = "Windows PC"

# Catalog search. IB v1.13.6: live filter is /games?q=...  /games?search= does not filter.
# Fill #game-search. Never fill #platforms-search ("Search for platform").
CATALOG_QUERY_PARAM = "q"
GAME_SEARCH_SELECTORS = (
    "#game-search",
    'input[placeholder="Search for a game"]',
    'input[placeholder*="Search for a game" i]',
)
RELATED_NAV_SELECTOR = "ul.related-games-nav a"

RELATED_NAV_RE = re.compile(
    r"(EDITION|REMAKE|DLC|BUNDLE|PACK|ADDON|ADD-ON|EXPANSION|ADDITIONAL|EXTRA|CONTENT|MOD)",
    re.I,
)


def is_filter_search_box(element_id: str = "", placeholder: str = "") -> bool:
    """True for sidebar filter search, not the games catalog box."""
    eid = (element_id or "").strip().lower()
    ph = (placeholder or "").strip().lower()
    if eid == "game-search" or "game" in ph:
        return False
    if eid in {"platforms-search", "genres-search"}:
        return True
    return "platform" in ph or "genre" in ph or eid.endswith("-search")


def is_parent_game_url(url: str, slug: str) -> bool:
    """True only for /games/{slug}, not sibling slugs such as hades vs hades--1."""
    path = urlparse(url or "").path.rstrip("/")
    slug = (slug or "").strip().strip("/")
    if slug.startswith("games/"):
        slug = slug.split("/", 1)[1]
    return bool(slug) and path == f"/games/{slug}"


def catalog_search_path(query: str) -> str:
    """Path that matches live IB catalog search after submit."""
    q = (query or "").strip()
    return f"/games?{CATALOG_QUERY_PARAM}={quote(q)}"


SKIP_FIELD_RE = re.compile(
    r"acquisit|source|amount|note|price|cost|borrow|lent|condition|region",
    re.I,
)

RATING_SCORE_LABELS = {
    1: "Disaster",
    2: "Painful",
    3: "Awful",
    4: "Bad",
    5: "Mediocre",
    6: "Okay",
    7: "Good",
    8: "Great",
    9: "Amazing",
    10: "Masterpiece",
}

RATING_WIDGET_LABELS = {
    "score": "Overall Rating",
    "overall": "Overall Rating",
    "gameplay": "Gameplay",
    "story": "Story",
    "sound": "Audio",
    "audio": "Audio",
    "visual": "Visual",
    "accessibility": "Playability",
    "playability": "Playability",
}

RATING_API_FIELDS = {
    "score": "score",
    "overall": "score",
    "gameplay": "gameplay",
    "story": "story",
    "sound": "sound",
    "audio": "sound",
    "visual": "visual",
    "accessibility": "accessibility",
    "playability": "accessibility",
}

STATUS_ALIASES = {
    "nostatus": "noStatus",
    "no status": "noStatus",
    "unplayed": "unplayed",
    "playing": "playing",
    "played": "played",
}

STATUS_NAMES = {
    "noStatus": "No Status",
    "unplayed": "Unplayed",
    "playing": "Playing",
    "played": "Played",
}

COMPLETION_ALIASES = {
    "nostatus": "noStatus",
    "no status": "noStatus",
    "notstarted": "notStarted",
    "not started": "notStarted",
    "unfinished": "unfinished",
    "beaten": "campaignCompleted",
    "campaigncompleted": "campaignCompleted",
    "completed": "completed",
    "continuous": "continuous",
    "dropped": "dropped",
}

COMPLETION_NAMES = {
    "noStatus": "No Status",
    "notStarted": "Not Started",
    "unfinished": "Unfinished",
    "campaignCompleted": "Beaten",
    "completed": "Completed",
    "continuous": "Continuous",
    "dropped": "Dropped",
}

ACQUISITION_NAMES = {
    "purchase": "Purchase",
    "gift": "Gift",
    "trade": "Trade",
    "keyBundle": "Key Bundle",
    "promotionalCopy": "Promotional Copy",
    "reviewCopy": "Review Copy",
    "free": "Free",
    "freeToPlay": "Free-to-play",
}

ACQUISITION_ALIASES = {
    "purchase": "purchase",
    "bought": "purchase",
    "buy": "purchase",
    "gift": "gift",
    "gifted": "gift",
    "trade": "trade",
    "key bundle": "keyBundle",
    "keybundle": "keyBundle",
    "promotional copy": "promotionalCopy",
    "promotionalcopy": "promotionalCopy",
    "review copy": "reviewCopy",
    "reviewcopy": "reviewCopy",
    "free": "free",
    "free to play": "freeToPlay",
    "freetoplay": "freeToPlay",
    "free-to-play": "freeToPlay",
}

DIGITAL_STORE_NAMES = {
    "steam": "Steam",
    "epicGameStore": "Epic Games",
    "gog": "GOG",
    "xboxLive": "Xbox",
    "uplay": "Ubisoft Connect",
    "rockstarStore": "Rockstar Games",
    "battleNetShop": "Battle.net",
    "origin": "EA",
    "itchIo": "itch.io",
    "discord": "Discord",
    "indieGala": "IndieGala",
    "nutaku": "Nutaku",
    "amazon": "Amazon",
    "bigFish": "Big Fish",
    "legacyGames": "Legacy Games",
    "stove": "Stove",
    "flashpoint": "Flashpoint",
}

PLAY_RECORD_TYPES = ("keyValue", "checkbox", "progress", "table")
PLAY_RECORD_TYPE_ALIASES = {
    "keyvalue": "keyValue",
    "key-value": "keyValue",
    "key value": "keyValue",
    "key-value pair": "keyValue",
    "key value pair": "keyValue",
    "checkbox": "checkbox",
    "progress": "progress",
    "table": "table",
}

REVIEW_MIN_PUBLISH_CHARS = 800


def env_bool(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off")


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def viewport() -> dict[str, int]:
    width = env_int("IB_VIEWPORT_WIDTH", 1280)
    height = env_int("IB_VIEWPORT_HEIGHT", 800)
    return {
        "width": max(320, min(width, 3840)),
        "height": max(240, min(height, 2160)),
    }


def setup_logging() -> logging.Logger:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )
    return logging.getLogger("infinitebacklog-mcp")


logger = setup_logging()


def project_root() -> Path:
    """Directory that holds pyproject.toml, or the process working directory."""
    cwd = Path.cwd()
    if (cwd / "pyproject.toml").is_file():
        return cwd
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file() and (parent / "src").is_dir():
            return parent
    return cwd


def load_project_env(root: Path | None = None) -> None:
    """Read KEY=VALUE lines from the project .env. Existing process values stay."""
    path = (root or project_root()) / ".env"
    if not path.is_file():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        logger.info("Could not read the project .env file")
        return
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ[key] = value


def playwright_profile_dir() -> Path:
    path = project_root() / ".playwright" / "ib-profile"
    path.mkdir(parents=True, exist_ok=True)
    return path


load_project_env()
