"""MCP tools: sign-in."""
from __future__ import annotations

from .. import browser as browser_mod
from ..browser import _ensure_browser, locked_tool
from ..login import credentials, signed_in_username
from ..normalize import _dumps


async def login(headless: bool = True) -> str:
    """Sign in with IB_USERNAME and IB_PASSWORD from the environment.

    Types them into the Infinite Backlog login form. If either value is missing,
    nothing is typed. Use the Playwright window instead (open_site with headless=false).
    """
    username, password = credentials()
    if not username or not password:
        return _dumps(
            {
                "ok": False,
                "error": "credentials_missing",
                "hint": (
                    "Set IB_USERNAME and IB_PASSWORD in .env, "
                    "or sign in once in the Playwright window."
                ),
            }
        )
    del password
    browser_mod._login_result = ""
    page = await _ensure_browser(headless=headless)
    if browser_mod._login_result == "ok":
        name = await signed_in_username(page)
        return _dumps({"ok": True, "username": name or username})
    return _dumps(
        {
            "ok": False,
            "error": "login_failed",
            "hint": (
                "Sign-in did not finish. Open the Playwright window "
                "with headless=false and sign in there."
            ),
        }
    )


def register(mcp) -> None:
    mcp.tool()(locked_tool(login))
