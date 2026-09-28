"""MCP tools: related."""
from __future__ import annotations

import re
from typing import Any

from ..browser import _ensure_browser, _goto_ib, locked_tool
from ..js import (
    ADDON_BOX_STATE_JS,
    PARENT_FORM_SNAPSHOT_JS,
    SELECT_DLC_OPTION_JS,
    TICK_ONE_ADDON_JS,
)
from ..matching import (
    _find_addition,
    _flatten_related,
    _game_id_from_hit,
    _kind_from_label,
    _match_item,
    _owned_title_hit,
    _parse_names,
)
from ..normalize import _dumps
from ..pages import (
    _click_update_game,
    _collection_rows_for_game,
    _logged_in_user,
    _page_igdb_id,
    _parent_collection_row,
    _scrape_collection_menus,
    _scrape_related_content,
    _wait_collection_edit,
    _wait_left_edit_form,
)
from ..security import SecurityError, parse_collection_edit_path, sanitize_collection_id, sanitize_slug, sanitize_username

async def list_related_content(game_slug: str, wait_ms: int = 3000) -> str:
    """List every RELATED GAMES & CONTENT tab on a game page: editions, DLC, packs, add-ons, remakes, bundles, and any other live section. Expands each tab before scraping."""
    slug = sanitize_slug(game_slug)
    page = await _ensure_browser()
    await _goto_ib(page, f"/games/{slug}", wait_ms)
    try:
        related = await _scrape_related_content(page, slug, wait_ms)
    except Exception as e:
        return _dumps(
            {
                "error": "scrape_failed",
                "detail": str(e),
                "url": page.url,
                "parent_slug": slug,
            }
        )
    related["counts"] = {
        section["label"]: len(section.get("items") or [])
        for section in related.get("sections") or []
    }
    kinds = {}
    for item in _flatten_related(related):
        kinds[item.get("kind") or "other"] = kinds.get(item.get("kind") or "other", 0) + 1
    related["kind_counts"] = kinds
    related["url"] = page.url
    return _dumps(related)

async def list_collection_content_menus(edit_path: str, wait_ms: int = 3000) -> str:
    """List extras widgets on a collection edit form: Add DLC dropdown, owned DLC, addon/pack checkboxes, GAME EDITION text, and other extras menus. Wait for UPDATE GAME. Requires login. Does not change the form."""
    path = parse_collection_edit_path(edit_path)
    page = await _ensure_browser()
    await _goto_ib(page, path, wait_ms)
    ready = await _wait_collection_edit(page, wait_ms)
    text = " ".join((await page.inner_text("body")).split())[:400]
    if re.search(r"\bLOG IN\b", text) and "UPDATE GAME" not in text:
        return _dumps({"error": "not_logged_in", "url": page.url, "hint": "Sign in with IB_USERNAME and IB_PASSWORD in .env, or call open_site with headless=false and sign in once in the Playwright window."})
    if not ready:
        return _dumps({"error": "edit_form_not_ready", "url": page.url, "hint": "Wait for UPDATE GAME; SPA shell text is not enough."})
    menus = await _scrape_collection_menus(page)
    menus["parent_snapshot"] = await page.evaluate(PARENT_FORM_SNAPSHOT_JS)
    edition = None
    for sel in menus.get("selects") or []:
        if sel.get("id") == "edition-select" or (_kind_from_label(sel.get("label") or "") == "edition" and sel.get("role") != "add_dlc"):
            edition = next((o for o in sel.get("options") or [] if o.get("selected")), None)
            menus["selected_edition"] = edition
            break
    return _dumps(menus)

async def add_game_content(
    parent_slug: str,
    names: str,
    collection_id: str = "",
    platform: str = "",
    digital: bool | None = None,
    wait_ms: int = 3500,
) -> str:
    """Add owned extras on the parent collection edit form. `names` is a JSON array of Steam/IB titles. Searches DLC first, then PACK/ADDON, EDITIONS, and every extras widget before not_found. DLC is picked from Add DLC to your game; packs are ticked on the addon-* input (only if unchecked). One UPDATE GAME persists nested additions. Does not use /games/add for DLC/packs. Does not change edition, play status, Digital, or Acquisition Info. Never DELETE GAME. `platform` and `digital` are ignored for nested extras (the parent row already has those fields)."""
    wanted = _parse_names(names)
    if not wanted:
        return _dumps({"error": "no_names", "hint": "pass names as a JSON array string"})

    slug = sanitize_slug(parent_slug)
    page = await _ensure_browser()
    await _goto_ib(page, f"/games/{slug}", wait_ms)
    related = await _scrape_related_content(page, slug, wait_ms)
    parent_title = related.get("parent_title") or slug
    related_flat = _flatten_related(related)
    scanned = list(related.get("scanned_menus") or [])
    parent_game_id = await _page_igdb_id(page)

    username, user_id = await _logged_in_user(page)
    try:
        username = sanitize_username(username, allow_empty=True)
    except SecurityError:
        username = ""
    parent_row, parent_rows = await _parent_collection_row(page, user_id, parent_game_id, collection_id)
    if collection_id and parent_row is None and parent_rows:
        return _dumps(
            {
                "error": "collection_id_not_found",
                "collection_id": collection_id,
                "parent_rows": [r.get("id") for r in parent_rows],
            }
        )
    if parent_row is None and len(parent_rows) > 1:
        return _dumps(
            {
                "error": "collection_id_required",
                "hint": "Parent has more than one collection row. Pass collection_id.",
                "parent_rows": [r.get("id") for r in parent_rows],
            }
        )
    cid = str(parent_row.get("id")) if parent_row else str(collection_id or "").strip()
    cid = sanitize_collection_id(cid, allow_empty=True)
    if not username:
        return _dumps({"error": "not_logged_in", "url": page.url})
    if not cid:
        return _dumps(
            {
                "error": "no_parent_collection_row",
                "hint": "Log in and pass collection_id for /users/{user}/collection/{slug}/edit?id=...",
            }
        )

    edit_path = f"/users/{username}/collection/{slug}/edit?id={cid}"
    await _goto_ib(page, edit_path, wait_ms)
    ready = await _wait_collection_edit(page, wait_ms)
    body = " ".join((await page.inner_text("body")).split())[:500]
    if re.search(r"\bLOG IN\b", body) and "UPDATE GAME" not in body:
        return _dumps({"error": "not_logged_in", "url": page.url})
    if not ready:
        return _dumps({"error": "edit_form_not_ready", "url": page.url})

    menus = await _scrape_collection_menus(page)
    scanned.extend(menus.get("headingBits") or [])
    snapshot_before = await page.evaluate(PARENT_FORM_SNAPSHOT_JS)
    additions = list((parent_row or {}).get("additions") or [])
    owned_titles = list(menus.get("ownedDlc") or [])

    results: list[dict[str, Any]] = []
    extras_queue: list[dict[str, Any]] = []
    for name in wanted:
        prefer = "edition" if re.search(r"edition", name, re.I) else "dlc"
        hit = _match_item(name, related_flat, menus, parent_title, prefer)
        if not hit:
            hit = _match_item(name, related_flat, menus, parent_title, None)
        if not hit:
            results.append(
                {
                    "name": name,
                    "status": "not_found",
                    "scanned_menus": scanned,
                    "note": "Checked every related-content tab and every extras dropdown/checklist on the edit form.",
                }
            )
            continue

        kind = hit.get("kind") or hit.get("section_kind") or "other"
        gid = _game_id_from_hit(hit)
        row = {
            "name": name,
            "matched_title": hit.get("title"),
            "matched_kind": kind,
            "matched_section": hit.get("section"),
            "matched_in": hit.get("_matched_in"),
            "slug": hit.get("slug"),
            "source": hit.get("_source"),
            "game_id": gid,
        }

        if kind == "edition":
            row["status"] = "edition_only"
            row["note"] = "Found under EDITIONS. Parent edition was not changed."
            results.append(row)
            continue
        if kind in ("bundle", "remake"):
            row["status"] = "related_other"
            row["note"] = f"Found as {kind}; not added as a second base game."
            results.append(row)
            continue

        owned = _find_addition(name, parent_title, additions, gid)
        owned_label = _owned_title_hit(name, parent_title, owned_titles)
        if owned or owned_label:
            row["status"] = "already_owned"
            if owned:
                row["addition_id"] = owned.get("id")
                row["game_id"] = owned.get("game_id") or gid
            results.append(row)
            continue

        extras_queue.append({"name": name, "hit": hit, "row": row})
        results.append(row)

    changed = False
    for item in extras_queue:
        name = item["name"]
        row = item["row"]
        dlc = await page.evaluate(SELECT_DLC_OPTION_JS, {"wanted": name, "parentTitle": parent_title})
        if isinstance(dlc, dict) and dlc.get("picked"):
            row["status"] = "queued_dlc"
            row["form"] = dlc
            if dlc.get("game_id"):
                row["game_id"] = dlc.get("game_id")
            changed = True
            await page.wait_for_timeout(700)
            continue
        addon = await page.evaluate(TICK_ONE_ADDON_JS, {"wanted": name, "parentTitle": parent_title})
        await page.wait_for_timeout(500)
        if isinstance(addon, dict) and addon.get("status") in ("clicked", "already"):
            row["status"] = "queued_addon_tick" if addon.get("status") == "clicked" else "already_owned"
            row["form"] = addon
            if addon.get("game_id"):
                row["game_id"] = addon.get("game_id")
            if addon.get("status") == "clicked":
                changed = True
            continue
        row["status"] = "add_failed"
        row["form"] = {"dlc": dlc, "addon": addon}
        row["note"] = "Matched in related menus but was not on the Add DLC dropdown or addon-* checklist."

    snapshot_mid = await page.evaluate(PARENT_FORM_SNAPSHOT_JS)
    addon_state = await page.evaluate(ADDON_BOX_STATE_JS)
    update_report: dict[str, Any] = {"clicked": False, "skipped": None}
    if changed:
        update_report = await _click_update_game(page)
        await _wait_left_edit_form(page, cid)

    parent_after_rows = await _collection_rows_for_game(page, user_id, parent_game_id or 0)
    parent_after = None
    for r in parent_after_rows:
        if str(r.get("id")) == cid:
            parent_after = r
            break
    if parent_after is None and parent_after_rows:
        parent_after = parent_after_rows[0]
    additions_after = list((parent_after or {}).get("additions") or [])

    for row in results:
        if row.get("status") not in ("queued_dlc", "queued_addon_tick", "add_attempted"):
            continue
        found = _find_addition(row["name"], parent_title, additions_after, row.get("game_id"))
        if found:
            row["status"] = "added"
            row["addition_id"] = found.get("id")
            row["game_id"] = found.get("game_id") or row.get("game_id")
            row["completion"] = found.get("completion")
        else:
            row["status"] = "add_attempted"

    edition_after = ((parent_after or {}).get("edition") or {}).get("id")
    edition_before = ((parent_row or {}).get("edition") or {}).get("id")
    return _dumps(
        {
            "parent_slug": slug,
            "parent_title": parent_title,
            "parent_collection_id": cid,
            "parent_game_id": parent_game_id,
            "scanned_menus": scanned,
            "kind_counts": related.get("kind_counts"),
            "snapshot_before": snapshot_before,
            "snapshot_before_update": snapshot_mid,
            "addon_boxes": addon_state,
            "update": update_report,
            "parent_fields_unchanged": {
                "edition_id": edition_after == edition_before,
                "status": (parent_after or {}).get("status") == (parent_row or {}).get("status"),
                "completion": (parent_after or {}).get("completion") == (parent_row or {}).get("completion"),
                "physical": (parent_after or {}).get("physical") == (parent_row or {}).get("physical"),
                "ownership": (parent_after or {}).get("ownership") == (parent_row or {}).get("ownership"),
                "acquisition": (parent_after or {}).get("acquisition") == (parent_row or {}).get("acquisition"),
            },
            "ignored_params": {"platform": platform, "digital": digital},
            "results": results,
        }
    )


def register(mcp) -> None:
    mcp.tool()(locked_tool(list_related_content))
    mcp.tool()(locked_tool(list_collection_content_menus))
    mcp.tool()(locked_tool(add_game_content))
