"""Shared Playwright browser lifecycle for deterministic tools."""
from __future__ import annotations

import atexit
import asyncio
import functools
import os
import re
import urllib.request
from typing import Optional

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from .cdp_bridge import CdpOriginBridge
from .cdp_attach import (
    discover_endpoint_urls,
    fetch_debug_json,
    local_devtools_port_files,
    pick_ib_target,
    public_endpoint,
    same_ib_page,
    websocket_url_from_version,
)
from .config import (
    IB_ORIGIN,
    env_bool,
    load_project_env,
    logger,
    playwright_profile_dir,
    viewport,
)
from .security import (
    SecurityError,
    chromium_launch_args,
    clamp_wait_ms,
    ib_url_from_path,
    is_ib_origin,
)

_browser: Optional[Browser] = None
_context: Optional[BrowserContext] = None
_page: Optional[Page] = None
_playwright = None
_headless_mode: Optional[bool] = None
_attached: bool = False
_opened_page: bool = False
_attach_source: str = ""
_cdp_bridge: CdpOriginBridge | None = None
_tool_lock = asyncio.Lock()
_CDP_CONNECT_TIMEOUT_S = 20.0
_login_result: str = ""
_iframe_body: bytes | None = None
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def locked_tool(fn):
    """Serialize tool bodies and convert SecurityError into a JSON error payload."""
    from .normalize import _dumps

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        async with _tool_lock:
            try:
                return await fn(*args, **kwargs)
            except SecurityError as exc:
                return _dumps({"error": exc.code, "hint": str(exc)})

    return wrapper


async def recover_off_origin(page: Page) -> None:
    """If the page left IB, try to return, then raise."""
    if is_ib_origin(page.url):
        return
    try:
        await page.go_back(wait_until="domcontentloaded")
    except Exception:
        pass
    if is_ib_origin(page.url):
        raise SecurityError(
            "off_origin",
            "Navigation left infinitebacklog.net; returned to the previous page.",
        )
    try:
        await page.goto(f"{IB_ORIGIN}/", wait_until="domcontentloaded", timeout=60000)
    except Exception:
        pass
    if is_ib_origin(page.url):
        raise SecurityError(
            "off_origin",
            "Navigation left infinitebacklog.net; returned to the home page.",
        )
    raise SecurityError("off_origin", "Navigation left infinitebacklog.net.")


async def require_ib_page(page: Page) -> None:
    if not is_ib_origin(page.url):
        raise SecurityError(
            "off_origin",
            "Current page is not infinitebacklog.net. Call open_site first.",
        )


def session_mode() -> str:
    return "attached" if _attached else "launched"


def session_details() -> str:
    """Status lines for open_site and current_url. No cookies, no websocket URL."""
    lines = [f"mode={session_mode()}"]
    if _attached:
        if _attach_source:
            lines.append(f"browser={_attach_source}")
    else:
        lines.append(f"headless={_headless_mode}")
    return "\n".join(lines)


def _reset_session_state() -> None:
    global _browser, _context, _page, _playwright, _headless_mode
    global _attached, _opened_page, _attach_source, _cdp_bridge, _login_result
    _page = _context = _browser = _playwright = None
    _headless_mode = None
    _attached = False
    _opened_page = False
    _attach_source = ""
    _cdp_bridge = None
    _login_result = ""


async def _stop_playwright(playwright) -> None:
    if playwright is None:
        return
    try:
        await asyncio.wait_for(playwright.stop(), timeout=3)
    except Exception:
        logger.info("Playwright stop did not finish; leaving the driver")


async def _connect_cdp(playwright, endpoint: str):
    """Connect, or return None. A timeout discards the driver so the next call is fresh."""
    global _playwright
    try:
        return await asyncio.wait_for(
            playwright.chromium.connect_over_cdp(endpoint),
            timeout=_CDP_CONNECT_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        logger.info("CDP connect timed out for %s", public_endpoint(endpoint))
        await _stop_playwright(playwright)
        _playwright = None
        return None
    except Exception as exc:
        detail = re.sub(r"/devtools/browser/[A-Za-z0-9._-]+", "/devtools/browser/...", str(exc))
        logger.info("CDP connect failed for %s: %s", public_endpoint(endpoint), detail[:240])
        return None


async def _ib_pages(browser: Browser) -> list[tuple[BrowserContext, Page]]:
    found: list[tuple[BrowserContext, Page]] = []
    for context in list(browser.contexts):
        for page in list(context.pages):
            try:
                url = page.url
            except Exception:
                continue
            if is_ib_origin(url):
                found.append((context, page))
    return found


async def _wait_for_ib_pages(browser: Browser) -> list[tuple[BrowserContext, Page]]:
    found = await _ib_pages(browser)
    if found:
        return found
    for _ in range(20):
        await asyncio.sleep(0.1)
        found = await _ib_pages(browser)
        if found:
            return found
    return []


def _prefer_page(
    pages: list[tuple[BrowserContext, Page]],
    chosen_url: str = "",
) -> tuple[BrowserContext, Page]:
    if chosen_url:
        for context, page in pages:
            if same_ib_page(page.url, chosen_url):
                return context, page
    for context, page in pages:
        path = urlparse_path(page.url)
        if path.startswith("/users/"):
            return context, page
    return pages[0]


def urlparse_path(url: str) -> str:
    from urllib.parse import urlparse

    return urlparse(url or "").path or ""


async def _open_background_page(
    browser: Browser,
) -> tuple[BrowserContext, Page] | None:
    """Open one about:blank tab in the attached browser without focusing it."""
    before = {id(page) for context in browser.contexts for page in context.pages}
    try:
        session = await browser.new_browser_cdp_session()
    except Exception:
        logger.info("Could not open a browser CDP session for a background tab")
        return None
    try:
        await session.send(
            "Target.createTarget",
            {"url": "about:blank", "background": True},
        )
    except Exception:
        logger.info("Background tab create failed")
        return None
    finally:
        try:
            await session.detach()
        except Exception:
            pass
    for _ in range(30):
        for context in list(browser.contexts):
            for page in list(context.pages):
                if id(page) not in before:
                    return context, page
        await asyncio.sleep(0.1)
    logger.info("Background tab did not appear in Playwright")
    return None


async def _bind_attached_page(
    browser: Browser,
    chosen_url: str,
) -> tuple[BrowserContext, Page, bool] | None:
    pages = await _wait_for_ib_pages(browser)
    if chosen_url:
        if not pages:
            logger.info("CDP listed an Infinite Backlog tab that Playwright did not expose")
            return None
        context, page = _prefer_page(pages, chosen_url)
        return context, page, False
    if pages:
        context, page = _prefer_page(pages, "")
        return context, page, False
    opened = await _open_background_page(browser)
    if opened is None:
        return None
    context, page = opened
    return context, page, True


async def _disconnect_browser(browser: Browser | None) -> None:
    """Drop a CDP connection. Does not close the user's context or tabs."""
    if browser is None:
        return
    try:
        await browser.close()
    except Exception:
        logger.info("CDP disconnect failed")


async def _probe_cdp_endpoints() -> list[tuple[str, str, str | None, str, bool]]:
    """Return (source, http_url, ws_url, chosen_page_url, list_known).

    Endpoints that already have an Infinite Backlog tab come first.
    list_known is false when /json/list is missing, which happens on some
    inspect-toggle debug ports. Those still connect via the port-file websocket.
    """
    env_url = os.environ.get("IB_CDP_URL", "")
    endpoints = discover_endpoint_urls(
        env_url=env_url,
        port_files=local_devtools_port_files(),
        include_probe=not (env_url or "").strip(),
    )
    ready: list[tuple[str, str, str | None, str, bool]] = []
    plain: list[tuple[str, str, str | None, str, bool]] = []
    for source, http_url, file_ws in endpoints:
        version = await asyncio.to_thread(fetch_debug_json, http_url, "version")
        ws_url = websocket_url_from_version(version) or file_ws
        if not isinstance(version, dict) and not ws_url:
            continue
        targets = await asyncio.to_thread(fetch_debug_json, http_url, "list")
        list_known = isinstance(targets, list)
        chosen = pick_ib_target(targets) if list_known else None
        row = (source, http_url, ws_url, str((chosen or {}).get("url") or ""), list_known)
        if chosen:
            ready.append(row)
        else:
            plain.append(row)
    ready.sort(key=lambda row: (0 if urlparse_path(row[3]).startswith("/users/") else 1, 0))
    return ready + plain


async def _attach_user_browser() -> bool:
    """Attach to an existing local browser. Never launches one."""
    global _browser, _context, _page, _playwright
    global _attached, _opened_page, _attach_source, _headless_mode, _cdp_bridge
    if not env_bool("IB_CDP", True):
        return False
    probed = await _probe_cdp_endpoints()
    if not probed:
        logger.info("No local browser debug port is listening")
        return False
    for source, http_url, ws_url, chosen_url, list_known in probed:
        if _playwright is None:
            _playwright = await async_playwright().start()
        version = await asyncio.to_thread(fetch_debug_json, http_url, "version")
        bridge: CdpOriginBridge | None = None
        if isinstance(version, dict):
            browser = await _connect_cdp(_playwright, http_url)
        else:
            browser = None
        if browser is None and ws_url:
            if _playwright is None:
                _playwright = await async_playwright().start()
            try:
                bridge = CdpOriginBridge(ws_url)
                await bridge.start()
                browser = await _connect_cdp(_playwright, bridge.http_url)
            except Exception:
                logger.info("CDP bridge failed source=%s", source)
                browser = None
            if browser is None and bridge is not None:
                await bridge.stop()
                bridge = None
        if browser is None:
            continue
        # An unknown target list must not be treated as "no IB tab".
        bound = await _bind_attached_page(browser, chosen_url if list_known else "")
        if bound is None:
            await _disconnect_browser(browser)
            if bridge is not None:
                await bridge.stop()
            continue
        context, page, opened = bound
        _browser = browser
        _context = context
        _page = page
        _attached = True
        _opened_page = opened
        _attach_source = source
        _cdp_bridge = bridge
        _headless_mode = False
        logger.info("Attached to existing browser source=%s", source)
        return True
    return False


def _login_status_iframe_body() -> bytes:
    """The Keycloak session iframe stalls in Chromium. Serve a finished copy instead."""
    global _iframe_body
    if _iframe_body is not None:
        return _iframe_body
    url = (
        "https://infinitebacklog.net/auth/realms/ib/"
        "protocol/openid-connect/login-status-iframe.html"
    )
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            _iframe_body = resp.read()
    except Exception:
        logger.info("Login status frame was not fetched; using an empty document")
        _iframe_body = b"<!doctype html><html><body></body></html>"
    return _iframe_body


async def _route_login_iframe(context: BrowserContext) -> None:
    async def handle(route) -> None:
        body = await asyncio.to_thread(_login_status_iframe_body)
        await route.fulfill(
            status=200,
            headers={"content-type": "text/html; charset=utf-8"},
            body=body,
        )

    await context.route("**/login-status-iframe.html", handle)


async def _launch_playwright(headless: bool) -> Page:
    """Open this server's Chromium profile. Does not attach to another browser."""
    global _browser, _context, _page, _playwright, _headless_mode
    global _attached, _opened_page, _attach_source
    if _playwright is None:
        _playwright = await async_playwright().start()
    try:
        _context = await _playwright.chromium.launch_persistent_context(
            user_data_dir=str(playwright_profile_dir()),
            headless=headless,
            viewport=viewport(),
            user_agent=_USER_AGENT,
            args=chromium_launch_args(),
        )
    except Exception as exc:
        raise SecurityError(
            "browser_start_failed",
            "Playwright did not start. Close a leftover Playwright window from this server and try again.",
        ) from exc
    await _route_login_iframe(_context)
    _browser = _context.browser
    _headless_mode = headless
    _attached = False
    _opened_page = True
    _attach_source = ""
    pages = [item for item in _context.pages if not item.is_closed()]
    _page = pages[0] if pages else await _context.new_page()
    if _page.url and "infinitebacklog.net" in _page.url:
        try:
            await _page.reload(wait_until="domcontentloaded", timeout=60000)
        except Exception:
            logger.info("Playwright page did not reload")
    logger.info("Playwright Chromium started headless=%s", headless)
    return _page


async def _maybe_login(page: Page) -> None:
    """Use .env credentials when both are set. Skip when either is missing."""
    global _login_result
    from .login import credentials, login_from_env

    if _login_result in {"ok", "failed"}:
        return
    username, password = credentials()
    if not username or not password:
        return
    result = await login_from_env(page)
    _login_result = "ok" if result.get("ok") else "failed"
    if not result.get("ok"):
        logger.info("Sign-in did not complete")


async def _ensure_browser(headless: bool | None = None) -> Page:
    global _browser, _context, _page, _playwright, _headless_mode
    global _attached, _opened_page, _attach_source
    load_project_env()
    if headless is None:
        headless = env_bool("IB_HEADLESS", True)
    if _attached:
        await _close_browser()
    if _page is not None and not _page.is_closed():
        if headless is False and _headless_mode is True:
            await _close_browser()
        else:
            await _maybe_login(_page)
            return _page
    if (
        _browser is not None
        and _headless_mode is not None
        and _headless_mode != headless
    ):
        await _close_browser()
    if _context is None or _browser is None or not _browser.is_connected():
        await _launch_playwright(headless)
    if _page is None or _page.is_closed():
        assert _context is not None
        pages = [item for item in _context.pages if not item.is_closed()]
        _page = pages[0] if pages else await _context.new_page()
        _opened_page = True
    await _maybe_login(_page)
    return _page


async def _close_browser() -> None:
    had_session = _browser is not None or _playwright is not None
    attached = _attached
    opened = _opened_page
    page = _page
    context = _context
    browser = _browser
    playwright = _playwright
    bridge = _cdp_bridge
    if attached:
        if opened and page is not None:
            try:
                if not page.is_closed():
                    await page.close()
            except Exception:
                logger.info("Could not close the tab this server opened")
        await _disconnect_browser(browser)
        if bridge is not None:
            await bridge.stop()
        await _stop_playwright(playwright)
        _reset_session_state()
        if had_session:
            logger.info("Disconnected from attached browser")
        return
    if page is not None and not page.is_closed():
        await page.close()
    if context is not None:
        await context.close()
    if browser is not None:
        await browser.close()
    if playwright is not None:
        await playwright.stop()
    _reset_session_state()
    if had_session:
        logger.info("Playwright browser closed")


async def _goto_ib(page: Page, path: str, wait_ms: int = 2000) -> None:
    wait_ms = clamp_wait_ms(wait_ms)
    url = ib_url_from_path(path)
    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(wait_ms)
    try:
        await page.wait_for_selector("#app", timeout=min(max(wait_ms, 2000), 12000))
    except Exception:
        pass
    await _wait_spa_text(page, timeout_ms=min(max(wait_ms, 2000), 8000))
    await recover_off_origin(page)


async def _wait_spa_text(page: Page, min_chars: int = 400, timeout_ms: int = 8000) -> None:
    """Wait until the Vue app has real content. ~281 chars is the chrome shell without h1."""
    try:
        await page.wait_for_function(
            """(min) => {
              const t = (document.body && document.body.innerText || '').trim();
              if (t.length > min) return true;
              const h1 = document.querySelector('h1');
              if (h1 && (h1.innerText || '').trim()) return true;
              if (document.querySelector('#game-search')) return true;
              return false;
            }""",
            arg=int(min_chars),
            timeout=timeout_ms,
        )
    except Exception:
        pass


def _sync_close_browser() -> None:
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_close_browser())
        else:
            loop.run_until_complete(_close_browser())
    except Exception:
        pass


atexit.register(_sync_close_browser)
