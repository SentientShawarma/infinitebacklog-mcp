"""MCP tools: navigation."""
from __future__ import annotations

from .. import browser as browser_mod
from ..browser import _close_browser, _ensure_browser, _goto_ib, locked_tool
from ..security import ib_url_from_path


async def open_site(path: str = "/", wait_ms: int = 2000, headless: bool = True) -> str:
    """Open a page on infinitebacklog.net in this server's Playwright window.

    Pass headless=false to show that window and sign in once. Later calls reuse the same profile.
    """
    ib_url_from_path(path)
    page = await _ensure_browser(headless=headless)
    await _goto_ib(page, path, wait_ms)
    title = await page.title()
    return f"Opened {page.url}\nTitle: {title}\n{browser_mod.session_details()}"


async def current_url() -> str:
    """Return the current URL, title, and whether Playwright is headless."""
    page = await _ensure_browser()
    title = await page.title()
    return f"URL: {page.url}\nTitle: {title}\n{browser_mod.session_details()}"


async def close_browser() -> str:
    """Close the Playwright window. Brave, Chrome, and Edge stay open."""
    await _close_browser()
    return "Playwright window closed."


def register(mcp) -> None:
    mcp.tool()(locked_tool(open_site))
    mcp.tool()(locked_tool(current_url))
    mcp.tool()(locked_tool(close_browser))
