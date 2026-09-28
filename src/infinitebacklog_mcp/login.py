"""Sign in through the Infinite Backlog login form.

The form is Keycloak: username or email, password, and a remember-me box.
This module types those fields. It does not read a browser cookie file.
"""
from __future__ import annotations

import os

from playwright.async_api import Page

from .config import IB_ORIGIN, logger

_AUTH_URL = (
    "https://infinitebacklog.net/auth/realms/ib/protocol/openid-connect/auth"
    "?client_id=web-application"
    "&redirect_uri=https%3A%2F%2Finfinitebacklog.net%2F"
    "&response_type=code"
    "&scope=openid"
)


def credentials() -> tuple[str, str]:
    username = os.environ.get("IB_USERNAME", "").strip()
    password = os.environ.get("IB_PASSWORD", "")
    if not username or not password:
        return "", ""
    return username, password


def redact(text: str, secret: str) -> str:
    if not secret or not text or secret not in text:
        return text
    return text.replace(secret, "")


def login_failure(secret: str = "") -> dict[str, object]:
    """Public failure payload. The password is never one of the fields."""
    hint = (
        "Infinite Backlog did not accept those credentials. "
        "Sign in in the Playwright window if you need to."
    )
    return {"ok": False, "error": "login_failed", "hint": redact(hint, secret)}


def _public(ok: bool, **fields: str) -> dict[str, object]:
    payload: dict[str, object] = {"ok": ok}
    payload.update(fields)
    return payload


async def _set_login_field(field, value: str) -> None:
    try:
        await field.fill(value, timeout=8000)
    except Exception:
        await field.evaluate(
            """(el, val) => {
              const proto = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
              proto.call(el, val);
              el.dispatchEvent(new Event('input', { bubbles: true }));
              el.dispatchEvent(new Event('change', { bubbles: true }));
              el.blur();
            }""",
            value,
        )


async def _clear_password(page: Page) -> None:
    try:
        await page.evaluate(
            """() => {
              const field = document.querySelector('#password');
              if (field) field.value = '';
            }"""
        )
    except Exception:
        return


async def signed_in_username(page: Page) -> str:
    try:
        name = await page.evaluate(
            """() => {
              const href = [...document.querySelectorAll('a[href^="/users/"]')]
                .map(el => el.getAttribute('href') || '')
                .find(h => /^\\/users\\/[^/]+$/.test(h));
              return href ? href.split('/').pop() : '';
            }"""
        )
    except Exception:
        return ""
    return str(name or "")


async def login_from_env(page: Page) -> dict[str, object]:
    """Type IB_USERNAME and IB_PASSWORD into the Keycloak form.

    Returns a small status dict. The password is not in that dict and is not logged.
    """
    username, password = credentials()
    if not username or not password:
        return _public(
            False,
            error="credentials_missing",
            hint=(
                "Set IB_USERNAME and IB_PASSWORD in .env, "
                "or sign in once in the Playwright window."
            ),
        )
    try:
        current = await signed_in_username(page)
        if current:
            return _public(True, status="already", username=current)
        await page.goto(f"{IB_ORIGIN}/", wait_until="domcontentloaded", timeout=60000)
        visible_login = page.locator("li.nav-item.login >> visible=true")
        try:
            await visible_login.first.wait_for(state="visible", timeout=30000)
        except Exception:
            current = await signed_in_username(page)
            if current:
                return _public(True, status="already", username=current)
            raise
        current = await signed_in_username(page)
        if current:
            return _public(True, status="already", username=current)
        await visible_login.first.click()
        try:
            await page.wait_for_selector("#username", timeout=20000)
        except Exception:
            await page.goto(_AUTH_URL, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_selector("#username", timeout=20000)
        form = page.locator("#kc-form-login")
        await form.wait_for(state="visible", timeout=20000)
        await _set_login_field(form.locator("#username"), username)
        await _set_login_field(form.locator("#password"), password)
        remember = form.locator("#rememberMe")
        if await remember.count():
            await remember.evaluate(
                """el => {
                  if (!el.checked) el.click();
                }"""
            )
        await form.locator("#kc-login").click(timeout=8000)
        try:
            await page.wait_for_function(
                """() => {
                  if (location.pathname.includes('/auth/')) {
                    const text = document.body ? document.body.innerText : '';
                    return /invalid username or password|account is disabled|update password/i.test(text);
                  }
                  const href = [...document.querySelectorAll('a[href^="/users/"]')]
                    .map(el => el.getAttribute('href') || '')
                    .find(h => /^\\/users\\/[^/]+$/.test(h));
                  if (href) return true;
                  const text = document.body ? document.body.innerText : '';
                  return /\\bLOG IN\\b/i.test(text) && !location.hash.includes('code=');
                }""",
                timeout=30000,
            )
        except Exception:
            await _clear_password(page)
            return login_failure(password)
        if "/auth/" in (page.url or ""):
            await _clear_password(page)
            return login_failure(password)
        current = await signed_in_username(page)
        if not current:
            return login_failure(password)
        return _public(True, status="signed_in", username=current)
    except Exception as exc:
        logger.info("Sign-in stopped at %s", type(exc).__name__)
        return login_failure(password)
    finally:
        password = ""
