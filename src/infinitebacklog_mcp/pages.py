"""Shared page navigation, scraping, and collection helpers."""
from __future__ import annotations

import re
from typing import Any, Optional
from urllib.parse import quote

from playwright.async_api import Page

from .browser import _goto_ib
from .config import RELATED_NAV_RE, RELATED_NAV_SELECTOR, is_parent_game_url
from .security import (
    SecurityError,
    api_fetch_path,
    clamp_wait_ms,
    sanitize_collection_id,
    sanitize_slug,
    sanitize_username,
)
from .js import (
    CLICK_EXACT_BUTTON_JS,
    CLICK_RELATED_TAB_JS,
    FETCH_API_JS,
    READ_MENUS_JS,
    REVEAL_RATING_CARD_JS,
    SCRAPE_CARDS_JS,
)
from .matching import _kind_from_label
from .normalize import profile_scope, slim_collection_row

async def _scrape_related_content(page: Page, parent_slug: str, wait_ms: int) -> dict[str, Any]:
    parent_title = ""
    try:
        parent_title = (await page.locator("h1").first.inner_text()).strip()
    except Exception:
        parent_title = parent_slug

    sections: list[dict[str, Any]] = []
    scanned_labels: list[str] = []

    async def collect(section_label: str) -> None:
        await page.wait_for_timeout(max(900, wait_ms // 4))
        cards = await page.evaluate(SCRAPE_CARDS_JS, parent_slug)
        items = []
        for card in cards or []:
            item_label = card.get("itemLabel") or section_label
            item_kind = _kind_from_label(item_label) if card.get("itemLabel") else _kind_from_label(section_label)
            if item_kind == "other":
                item_kind = _kind_from_label(section_label)
            items.append(
                {
                    "label": item_label,
                    "kind": item_kind,
                    "title": card.get("title") or card.get("slug"),
                    "slug": card.get("slug"),
                    "href": card.get("href"),
                }
            )
        sections.append(
            {
                "label": section_label,
                "kind": _kind_from_label(section_label),
                "items": items,
            }
        )

    async def stay_on_parent() -> bool:
        if is_parent_game_url(page.url, parent_slug):
            return True
        try:
            await page.go_back(wait_until="domcontentloaded")
            await page.wait_for_timeout(400)
        except Exception:
            pass
        if not is_parent_game_url(page.url, parent_slug):
            await _goto_ib(page, f"/games/{sanitize_slug(parent_slug)}", max(wait_ms, 1500))
        return is_parent_game_url(page.url, parent_slug)

    # One tab is valid (Hades 2020 is EDITIONS only). Do not require >= 2.
    # Do not click page-wide EDITION/DLC labels: those are other-game cards.
    tab_labels: list[str] = []
    try:
        await page.wait_for_function(
            f"() => document.querySelectorAll({RELATED_NAV_SELECTOR!r}).length >= 1",
            timeout=min(max(wait_ms, 2500), 8000),
        )
        tab_labels = await page.evaluate(
            f"""() => [...document.querySelectorAll({RELATED_NAV_SELECTOR!r})]
                .map(a => (a.innerText || '').trim())
                .filter(Boolean)"""
        )
    except Exception:
        tab_labels = []

    if tab_labels:
        for label in tab_labels:
            scanned_labels.append(label)
            try:
                await page.evaluate(CLICK_RELATED_TAB_JS, label)
                await page.wait_for_timeout(500)
                if not await stay_on_parent():
                    continue
                try:
                    await page.wait_for_function(
                        """(wanted) => {
                          const active = document.querySelector('ul.related-games-nav li.active, ul.related-games-nav .active');
                          return !!(active && (active.innerText || '').trim().includes(wanted.split(' (')[0]));
                        }""",
                        arg=label,
                        timeout=4000,
                    )
                except Exception:
                    pass
            except Exception:
                await stay_on_parent()
            if is_parent_game_url(page.url, parent_slug):
                await collect(label)
    else:
        await collect("RELATED")

    return {
        "parent_slug": parent_slug,
        "parent_title": parent_title,
        "scanned_menus": scanned_labels,
        "sections": sections,
    }


async def _scrape_collection_menus(page: Page) -> dict[str, Any]:
    data = await page.evaluate(READ_MENUS_JS)
    selects = []
    for sel in data.get("selects") or []:
        label = sel.get("label") or sel.get("id") or sel.get("name") or ""
        kind = _kind_from_label(label + " " + (sel.get("id") or ""))
        options = []
        is_dlc_add = False
        for opt in sel.get("options") or []:
            text = (opt.get("text") or "").strip()
            if re.search(r"Add DLC to your game", text, re.I):
                is_dlc_add = True
            value = opt.get("value")
            game_id = int(value) if str(value).isdigit() else None
            options.append({**opt, "text": text, "game_id": game_id})
        if is_dlc_add:
            kind = "dlc"
        selects.append(
            {
                **sel,
                "options": options,
                "kind": kind,
                "role": "add_dlc" if is_dlc_add else None,
                "extra": is_dlc_add or bool(RELATED_NAV_RE.search(label + " " + (sel.get("id") or ""))),
            }
        )
    checkboxes = []
    for box in data.get("checkboxes") or []:
        label = box.get("label") or box.get("id") or ""
        box_id = box.get("id") or ""
        if re.search(r"^(digital|physical|favourite|favorite)$", box_id, re.I):
            continue
        kind = _kind_from_label(label)
        gid = None
        m = re.match(r"addon-(\d+)$", box_id, re.I)
        if m:
            kind = "pack_addon"
            gid = int(m.group(1))
        checkboxes.append({**box, "kind": kind, "game_id": gid})
    return {
        "selects": selects,
        "checkboxes": checkboxes,
        "headingBits": data.get("headingBits") or [],
        "dlcSelect": data.get("dlcSelect"),
        "addonBoxes": data.get("addonBoxes") or [],
        "editionText": data.get("editionText") or "",
        "ownedDlc": data.get("ownedDlc") or [],
        "url": page.url,
    }


async def _page_igdb_id(page: Page) -> Optional[int]:
    try:
        raw = await page.evaluate(
            """() => {
              const t = document.body.innerText || '';
              const m = t.match(/IGDB ID\\s+(\\d+)/i);
              return m ? m[1] : null;
            }"""
        )
        return int(raw) if raw else None
    except Exception:
        return None


def user_id_from_search(username: str, rows: Any) -> int:
    """Pick the search row whose username matches. Never use the first row."""
    wanted = (username or "").casefold()
    if not wanted or not isinstance(rows, list):
        return 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("username") or "")
        if name.casefold() != wanted:
            continue
        try:
            return int(row.get("id") or 0)
        except (TypeError, ValueError):
            return 0
    return 0


def saved_delete_label(labels: Any) -> str | None:
    """The one saved-copy delete button, or None when it is missing or duplicated."""
    if not isinstance(labels, list):
        return None
    hits = [str(label).strip() for label in labels if str(label).strip().startswith("DELETE GAME FOR ")]
    if len(hits) != 1:
        return None
    return hits[0]


async def _user_id_for_username(page: Page, username: str) -> int:
    try:
        safe = sanitize_username(username)
    except SecurityError:
        return 0
    path = "/api/users?search=" + quote(safe, safe="")
    try:
        rows = await page.evaluate(
            """async (apiPath) => {
              const response = await fetch(apiPath, { credentials: 'include' });
              if (!response.ok) return [];
              const data = await response.json();
              return Array.isArray(data) ? data : [];
            }""",
            path,
        )
    except Exception:
        return 0
    return user_id_from_search(safe, rows)


async def _logged_in_user(page: Page) -> tuple[str, int]:
    try:
        info = await page.evaluate(
            """() => {
              const a = [...document.querySelectorAll('a[href^="/users/"]')]
                .map(x => x.getAttribute('href') || '')
                .find(h => /^\\/users\\/[^/]+$/.test(h) && !/log-?in|sign/i.test(h));
              const userId = window.user_id || window.userId || null;
              return { href: a || '', userId };
            }"""
        )
        href = (info or {}).get("href") or ""
        username = href.split("/")[-1] if href else ""
        uid = (info or {}).get("userId") or 0
        try:
            uid = int(uid)
        except (TypeError, ValueError):
            uid = 0
        if not uid and username:
            uid = await _user_id_for_username(page, username)
        return username or "", uid
    except Exception:
        return "", 0


async def _collection_rows_for_game(page: Page, user_id: int, game_id: int) -> list[dict[str, Any]]:
    if not user_id or not game_id:
        return []
    try:
        rows = await page.evaluate(
            """async ({ userId, gameId }) => {
              const r = await fetch('/api/user_collections?user_id=' + userId + '&game_id=' + gameId, { credentials: 'include' });
              if (!r.ok) return { error: r.status };
              return await r.json();
            }""",
            {"userId": user_id, "gameId": game_id},
        )
        if isinstance(rows, list):
            return rows
        return []
    except Exception:
        return []


async def _game_id_for_slug(page: Page, slug: str) -> Optional[int]:
    await _goto_ib(page, f"/games/{sanitize_slug(slug)}", wait_ms=2500)
    return await _page_igdb_id(page)


async def _wait_collection_edit(page: Page, wait_ms: int) -> bool:
    timeout = min(max(wait_ms + 4000, 8000), 20000)
    try:
        await page.wait_for_function(
            "() => (document.body.innerText || '').includes('UPDATE GAME') || (document.body.innerText || '').includes('ADD TO COLLECTION')",
            timeout=timeout,
        )
        return True
    except Exception:
        body = " ".join((await page.inner_text("body")).split())[:400]
        return "UPDATE GAME" in body or "ADD TO COLLECTION" in body


async def _wait_collection_view(page: Page, wait_ms: int) -> bool:
    timeout = min(max(wait_ms + 4000, 8000), 20000)
    try:
        await page.wait_for_function(
            "() => !!document.querySelector('.collection-rating') || (document.body.innerText || '').includes('COLLECTION GAME')",
            timeout=timeout,
        )
        return True
    except Exception:
        body = " ".join((await page.inner_text("body")).split())[:400]
        return "COLLECTION GAME" in body


async def _wait_review_form(page: Page, wait_ms: int) -> bool:
    timeout = min(max(wait_ms + 4000, 8000), 20000)
    try:
        await page.wait_for_function(
            "() => (document.body.innerText || '').includes('WRITE A REVIEW') && !!document.querySelector('.ProseMirror, #review-title, #spoilers')",
            timeout=timeout,
        )
        return True
    except Exception:
        body = " ".join((await page.inner_text("body")).split())[:400]
        return "WRITE A REVIEW" in body


async def _wait_left_edit_form(page: Page, cid: str, timeout: int = 15000) -> None:
    safe_id = sanitize_collection_id(cid, allow_empty=True)
    if not safe_id:
        await page.wait_for_timeout(2500)
        return
    try:
        await page.wait_for_function(
            """(id) => !location.href.includes('edit?id=' + id) || !(document.body.innerText || '').includes('UPDATE GAME')""",
            arg=safe_id,
            timeout=timeout,
        )
    except Exception:
        await page.wait_for_timeout(2500)


async def _fetch_ib_api(
    page: Page,
    path: str,
    method: str = "GET",
    body: Any = None,
) -> dict[str, Any]:
    if (method or "GET").upper() != "GET":
        raise SecurityError("invalid_api_method", "Only GET is allowed for IB API fetches.")
    safe = api_fetch_path(path)
    result = await page.evaluate(FETCH_API_JS, {"path": safe, "method": "GET", "body": body})
    return result if isinstance(result, dict) else {"ok": False, "status": 0, "data": result}


def _reviews_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("reviews", "data", "results"):
            val = payload.get(key)
            if isinstance(val, list):
                return [x for x in val if isinstance(x, dict)]
        if payload.get("id") and ("content" in payload or "body" in payload or "title" in payload):
            return [payload]
    return []


async def _resolve_game_context(
    page: Page,
    slug: str,
    collection_id: str = "",
    wait_ms: int = 2500,
) -> dict[str, Any]:
    wait_ms = clamp_wait_ms(wait_ms)
    raw = (slug or "").strip().strip("/")
    if raw.startswith("users/"):
        parts = [p for p in raw.split("/") if p]
        if "collection" in parts:
            raw = parts[parts.index("collection") + 1]
    slug = sanitize_slug(raw)
    collection_id = sanitize_collection_id(collection_id, allow_empty=True)
    await _goto_ib(page, f"/games/{slug}", wait_ms)
    game_id = await _page_igdb_id(page)
    username, user_id = await _logged_in_user(page)
    try:
        username = sanitize_username(username, allow_empty=True)
    except SecurityError:
        username = ""
    rows: list[dict[str, Any]] = []
    if game_id and user_id:
        rows = await _collection_rows_for_game(page, user_id, game_id)
    row, _ = await _parent_collection_row(page, user_id, game_id, collection_id)
    return {
        "slug": slug,
        "game_id": game_id,
        "username": username,
        "user_id": user_id,
        "rows": rows,
        "row": row,
        "url": page.url,
    }


async def _open_collection_edit(
    page: Page,
    username: str,
    slug: str,
    collection_id: str,
    wait_ms: int,
) -> dict[str, Any]:
    wait_ms = clamp_wait_ms(wait_ms)
    if not (username or "").strip():
        return {"error": "not_logged_in", "url": page.url}
    user = sanitize_username(username)
    safe_slug = sanitize_slug(slug)
    cid = sanitize_collection_id(collection_id, allow_empty=True)
    edit_path = f"/users/{user}/collection/{safe_slug}/edit"
    if cid:
        edit_path += f"?id={cid}"
    await _goto_ib(page, edit_path, wait_ms)
    ready = await _wait_collection_edit(page, wait_ms)
    body = " ".join((await page.inner_text("body")).split())[:500]
    if re.search(r"\bLOG IN\b", body) and "UPDATE GAME" not in body and "ADD TO COLLECTION" not in body:
        return {"error": "not_logged_in", "url": page.url}
    if not ready:
        return {"error": "edit_form_not_ready", "url": page.url}
    return {"ok": True, "url": page.url, "path": edit_path}


async def _open_collection_view(page: Page, username: str, slug: str, wait_ms: int) -> dict[str, Any]:
    wait_ms = clamp_wait_ms(wait_ms)
    if not (username or "").strip():
        return {"error": "not_logged_in", "url": page.url}
    path = f"/users/{sanitize_username(username)}/collection/{sanitize_slug(slug)}"
    await _goto_ib(page, path, wait_ms)
    ready = await _wait_collection_view(page, wait_ms)
    body = " ".join((await page.inner_text("body")).split())[:400]
    if re.search(r"\bLOG IN\b", body) and "COLLECTION GAME" not in body:
        return {"error": "not_logged_in", "url": page.url}
    if not ready:
        return {"error": "collection_view_not_ready", "url": page.url}
    return {"ok": True, "url": page.url}


async def _wait_play_records(page: Page, wait_ms: int) -> bool:
    timeout = min(max(wait_ms + 4000, 8000), 20000)
    try:
        await page.wait_for_function(
            "() => [...document.querySelectorAll('button')].some(b => /ADD CATEGORY/i.test(b.innerText || '')) || (document.body.innerText || '').includes('PLAY RECORDS')",
            timeout=timeout,
        )
        return True
    except Exception:
        body = " ".join((await page.inner_text("body")).split())[:400]
        return "PLAY RECORDS" in body


async def _open_play_records(
    page: Page,
    username: str,
    slug: str,
    collection_id: str,
    wait_ms: int,
) -> dict[str, Any]:
    wait_ms = clamp_wait_ms(wait_ms)
    if not (username or "").strip():
        return {"error": "not_logged_in", "url": page.url}
    cid = sanitize_collection_id(collection_id, allow_empty=True)
    path = f"/users/{sanitize_username(username)}/collection/{sanitize_slug(slug)}/edit/stats"
    if cid:
        path += f"?id={cid}"
    await _goto_ib(page, path, wait_ms)
    ready = await _wait_play_records(page, wait_ms)
    body = " ".join((await page.inner_text("body")).split())[:500]
    if re.search(r"\bLOG IN\b", body) and "PLAY RECORDS" not in body:
        return {"error": "not_logged_in", "url": page.url}
    if "/settings" in (page.url or "") or (
        "UNLOCK CUSTOM TAGS" in body and "ADD CATEGORY" not in body
    ):
        return profile_scope("settings_or_profile", {"url": page.url})
    if not ready:
        return {"error": "play_records_not_ready", "url": page.url, "hint": "Play Records is hidden when status is No Status."}
    return {"ok": True, "url": page.url, "path": path}


def _require_collection_id(ctx: dict[str, Any], collection_id: str, always: bool = False) -> dict[str, Any] | None:
    cid = str(collection_id or "").strip()
    if always and not cid and not (ctx.get("row") or {}).get("id"):
        return {
            "error": "collection_id_required",
            "hint": "Pass collection_id for this copy.",
            "parent_rows": [slim_collection_row(r) for r in (ctx.get("rows") or [])],
        }
    if len(ctx.get("rows") or []) > 1 and not cid:
        return {
            "error": "collection_id_required",
            "hint": "Parent has more than one collection row. Pass collection_id.",
            "parent_rows": [slim_collection_row(r) for r in ctx["rows"]],
        }
    return None


async def _click_exact_button(page: Page, exact: str) -> dict[str, Any]:
    loc = page.locator("button").filter(has_text=re.compile(rf"^{re.escape(exact)}$"))
    try:
        await loc.first.click(timeout=8000)
        return {"clicked": True, "text": exact}
    except Exception:
        return await page.evaluate(CLICK_EXACT_BUTTON_JS, {"exact": exact, "forbid": ""})


async def _click_update_game(page: Page) -> dict[str, Any]:
    return await _click_exact_button(page, "UPDATE GAME")


async def _page_has_rating_card(page: Page) -> bool:
    return bool(await page.evaluate("() => !!document.querySelector('.collection-rating')"))


async def _ensure_rating_card(
    page: Page,
    ctx: dict[str, Any],
    wait_ms: int,
) -> dict[str, Any]:
    """Mount .collection-rating. IB hides it while Unplayed/No Status; locally set Playing (no UPDATE GAME)."""
    view = await _open_collection_view(page, ctx["username"], ctx["slug"], wait_ms)
    if view.get("error"):
        return view
    if await _page_has_rating_card(page):
        return {"ok": True, "surface": "view", "revealed": False, "view": view}

    cid = str((ctx.get("row") or {}).get("id") or "")
    edit = await _open_collection_edit(page, ctx["username"], ctx["slug"], cid, wait_ms)
    if edit.get("error"):
        return edit
    if await _page_has_rating_card(page):
        return {"ok": True, "surface": "edit", "revealed": False, "edit": edit}

    reveal = await page.evaluate(REVEAL_RATING_CARD_JS)
    try:
        await page.wait_for_function(
            "() => !!document.querySelector('.collection-rating')",
            timeout=min(max(wait_ms + 2000, 5000), 12000),
        )
    except Exception:
        return {
            "error": "rating_card_unavailable",
            "hint": "IB only mounts .collection-rating when status is Playing or Played.",
            "reveal": reveal,
            "url": page.url,
        }
    return {
        "ok": True,
        "surface": "edit_revealed",
        "revealed": bool((reveal or {}).get("revealed")),
        "previous_status": (reveal or {}).get("previous_status"),
        "reveal": reveal,
        "edit": edit,
    }


async def _parent_collection_row(
    page: Page,
    user_id: int,
    parent_game_id: Optional[int],
    collection_id: str,
) -> tuple[Optional[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    if parent_game_id and user_id:
        rows = await _collection_rows_for_game(page, user_id, parent_game_id)
    if collection_id:
        cid = str(collection_id).strip()
        for row in rows:
            if str(row.get("id")) == cid:
                return row, rows
        return None, rows
    if len(rows) == 1:
        return rows[0], rows
    return None, rows

