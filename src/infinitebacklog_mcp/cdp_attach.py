"""Find a local browser that already has an Infinite Backlog tab.

Discovery reads DevToolsActivePort and the usual localhost debug port.
It does not launch a browser, and it does not read cookies.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .security import is_ib_origin

_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_PROBE_URL = "http://127.0.0.1:9222"


def is_local_endpoint(url: str) -> bool:
    """True for localhost HTTP or WebSocket debug endpoints."""
    try:
        parsed = urlparse((url or "").strip())
    except Exception:
        return False
    if parsed.scheme not in {"http", "https", "ws", "wss"}:
        return False
    if parsed.username or parsed.password:
        return False
    host = (parsed.hostname or "").lower().strip("[]")
    return host in _LOCAL_HOSTS


def parse_devtools_active_port(text: str) -> int | None:
    """First line of a DevToolsActivePort file is the debug port."""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if not lines:
        return None
    try:
        port = int(lines[0])
    except ValueError:
        return None
    if port < 1 or port > 65535:
        return None
    return port


def browser_label_from_path(path: Path) -> str:
    text = str(path).lower()
    if "brave" in text:
        return "brave"
    if "edge" in text:
        return "edge"
    if "chrome" in text:
        return "chrome"
    return "devtools"


def local_devtools_port_files(local_app_data: Path | None = None) -> list[Path]:
    """Default-profile DevToolsActivePort files for Brave, Chrome, and Edge."""
    root = local_app_data
    if root is None:
        raw = os.environ.get("LOCALAPPDATA", "").strip()
        if not raw:
            return []
        root = Path(raw)
    return [
        root / "BraveSoftware" / "Brave-Browser" / "User Data" / "DevToolsActivePort",
        root / "Google" / "Chrome" / "User Data" / "DevToolsActivePort",
        root / "Microsoft" / "Edge" / "User Data" / "DevToolsActivePort",
    ]


def _http_endpoint(port: int) -> str:
    return f"http://127.0.0.1:{port}"


_BROWSER_PATH_RE = re.compile(r"^/devtools/browser/[A-Za-z0-9._-]{1,128}$")


def websocket_from_port_text(text: str) -> str | None:
    """Build ws://127.0.0.1:{port}/devtools/browser/... from a DevToolsActivePort file."""
    port = parse_devtools_active_port(text)
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if port is None or len(lines) < 2:
        return None
    path = lines[1]
    if not _BROWSER_PATH_RE.fullmatch(path):
        return None
    return f"ws://127.0.0.1:{port}{path}"


def _normalize_endpoint(url: str) -> str | None:
    raw = (url or "").strip()
    if not raw:
        return None
    if "://" not in raw:
        raw = "http://" + raw
    if not is_local_endpoint(raw):
        return None
    parsed = urlparse(raw)
    scheme = "http" if parsed.scheme in {"http", "https"} else parsed.scheme
    host = parsed.hostname or "127.0.0.1"
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    port = f":{parsed.port}" if parsed.port else ""
    path = parsed.path or ""
    if path == "/":
        path = ""
    return f"{scheme}://{host}{port}{path}"


def discover_endpoint_urls(
    *,
    env_url: str = "",
    port_files: list[Path] | None = None,
    include_probe: bool = True,
) -> list[tuple[str, str, str | None]]:
    """Return (source, http_url, ws_url) in try order.

    An explicit IB_CDP_URL is used alone. Otherwise port files come first,
    then the default localhost:9222 probe. Non-local URLs are dropped.
    ws_url comes from a DevToolsActivePort browser path when /json/version is unavailable.
    """
    explicit = _normalize_endpoint(env_url)
    if explicit:
        http_url, ws_url = _split_endpoint(explicit.rstrip("/"))
        return [("env", http_url, ws_url)]

    found: list[tuple[str, str, str | None]] = []
    seen: set[str] = set()

    def add(source: str, http_url: str, ws_url: str | None = None) -> None:
        normalized = _normalize_endpoint(http_url)
        if not normalized:
            return
        key = normalized.rstrip("/")
        if key in seen:
            return
        seen.add(key)
        found.append((source, key, ws_url))

    for path in port_files if port_files is not None else local_devtools_port_files():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        port = parse_devtools_active_port(text)
        if port is None:
            continue
        add(browser_label_from_path(path), _http_endpoint(port), websocket_from_port_text(text))

    if include_probe:
        add("probe", _PROBE_URL, None)
    return found


def _split_endpoint(url: str) -> tuple[str, str | None]:
    parsed = urlparse(url)
    port = f":{parsed.port}" if parsed.port else ""
    host = parsed.hostname or "127.0.0.1"
    http_url = f"http://{host}{port}"
    if parsed.scheme in {"ws", "wss"}:
        return http_url, url
    return url, None


def public_endpoint(url: str) -> str:
    """Host and port only. Drops a /devtools/browser id."""
    try:
        parsed = urlparse((url or "").strip())
    except Exception:
        return "local"
    host = parsed.hostname or "local"
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{host}{port}"


def websocket_url_from_version(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    raw = str(payload.get("webSocketDebuggerUrl") or "").strip()
    if not raw:
        return None
    if not is_local_endpoint(raw):
        return None
    return raw


def pick_ib_target(targets: Any) -> dict[str, Any] | None:
    """Choose one page target on infinitebacklog.net.

    Collection URLs under /users/ win. Other tabs are ignored.
    """
    if not isinstance(targets, list):
        return None
    pages: list[dict[str, Any]] = []
    for item in targets:
        if not isinstance(item, dict):
            continue
        if str(item.get("type") or "page") != "page":
            continue
        url = str(item.get("url") or "")
        if not is_ib_origin(url):
            continue
        pages.append(item)
    if not pages:
        return None

    def rank(item: dict[str, Any]) -> tuple[int, int]:
        path = urlparse(str(item.get("url") or "")).path
        return (0 if path.startswith("/users/") else 1, 0)

    pages.sort(key=rank)
    return pages[0]


def same_ib_page(left: str, right: str) -> bool:
    if not is_ib_origin(left) or not is_ib_origin(right):
        return False
    a = urlparse(left)
    b = urlparse(right)
    return a.path.rstrip("/") == b.path.rstrip("/") and a.query == b.query


def debug_json_urls(http_url: str, leaf: str) -> list[str]:
    """Local /json/version and /json/list URLs, with and without a trailing slash."""
    base = (http_url or "").rstrip("/")
    name = (leaf or "").strip("/")
    if not base or not name:
        return []
    return [f"{base}/json/{name}", f"{base}/json/{name}/"]


def fetch_debug_json(http_url: str, leaf: str, timeout: float = 2.0) -> Any | None:
    """GET /json/version or /json/list, with and without the trailing slash Playwright uses."""
    for url in debug_json_urls(http_url, leaf):
        payload = fetch_json(url, timeout=timeout)
        if payload is not None:
            return payload
    return None


def fetch_json(url: str, timeout: float = 2.0) -> Any | None:
    """GET a localhost debug JSON endpoint. No Origin header, no cookie jar."""
    if not is_local_endpoint(url):
        return None
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(1_000_000)
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return None
