"""MCP tools: collection."""
from __future__ import annotations

import re
from typing import Any

from ..browser import _ensure_browser, locked_tool
from ..config import (
    ACQUISITION_NAMES,
    COMPLETION_NAMES,
    DIGITAL_STORE_NAMES,
    PLAY_RECORD_TYPES,
    RATING_SCORE_LABELS,
    REVIEW_MIN_PUBLISH_CHARS,
    STATUS_NAMES,
)
from ..js import (
    CLICK_NAMED_BUTTON_JS,
    FILL_PLATFORM_COPY_JS,
    LIST_PLATFORM_OPTIONS_JS,
    SET_ACQUISITION_FORM_JS,
    SET_PROGRESS_FORM_JS,
    SNAPSHOT_ACQUISITION_JS,
    SNAPSHOT_PLATFORM_TABS_JS,
    SNAPSHOT_PROGRESS_JS,
    SNAPSHOT_RATINGS_JS,
)
from ..normalize import (
    _alias_key,
    _dumps,
    _reviews_list,
    normalize_acquisition,
    normalize_completion,
    normalize_digital_store,
    normalize_platform_alias,
    normalize_status,
    parse_clear_fields,
    parse_progress_pct,
    slim_collection_row,
)
from ..pages import (
    _click_exact_button,
    _click_update_game,
    _collection_rows_for_game,
    _fetch_ib_api,
    _open_collection_edit,
    _open_collection_view,
    _require_collection_id,
    _resolve_game_context,
    _wait_left_edit_form,
    saved_delete_label,
)

async def list_collection_game_options(slug: str, collection_id: str = "", wait_ms: int = 3000) -> str:
    """Read-only dump of copies, extra-platform plus button, progress widgets, ratings, and reviews for a collection game. Does not save. Requires login."""
    page = await _ensure_browser()
    ctx = await _resolve_game_context(page, slug, collection_id, wait_ms)
    if not ctx.get("game_id"):
        return _dumps({"error": "game_not_found", "slug": ctx.get("slug"), "url": ctx.get("url")})
    if not ctx.get("rows"):
        body = " ".join((await page.inner_text("body")).split())[:300]
        if re.search(r"\bLOG IN\b", body):
            return _dumps({"error": "not_logged_in", "url": page.url})
        return _dumps(
            {
                "error": "no_collection_row",
                "slug": ctx["slug"],
                "game_id": ctx.get("game_id"),
                "hint": "Game is not in this user's collection.",
            }
        )

    rating = await _fetch_ib_api(page, f"/ratings?user_id={ctx['user_id']}&game_id={ctx['game_id']}")
    published = await _fetch_ib_api(
        page,
        f"/reviews?user_id={ctx['user_id']}&game_id={ctx['game_id']}&published=true",
    )
    drafts = await _fetch_ib_api(
        page,
        f"/reviews?user_id={ctx['user_id']}&game_id={ctx['game_id']}&published=false",
    )

    view = await _open_collection_view(page, ctx["username"], ctx["slug"], wait_ms)
    rating_widgets = None
    if view.get("ok"):
        rating_widgets = await page.evaluate(SNAPSHOT_RATINGS_JS)

    cid = str((ctx.get("row") or {}).get("id") or collection_id or "")
    edit = await _open_collection_edit(page, ctx["username"], ctx["slug"], cid, wait_ms)
    tabs = None
    progress = None
    acquisition = None
    if edit.get("ok"):
        tabs = await page.evaluate(SNAPSHOT_PLATFORM_TABS_JS)
        progress = await page.evaluate(SNAPSHOT_PROGRESS_JS)
        acquisition = await page.evaluate(SNAPSHOT_ACQUISITION_JS)

    rating_data = rating.get("data") if isinstance(rating.get("data"), dict) and rating.get("ok") else None
    return _dumps(
        {
            "slug": ctx["slug"],
            "game_id": ctx["game_id"],
            "username": ctx["username"],
            "user_id": ctx["user_id"],
            "copies": [slim_collection_row(r) for r in ctx["rows"]],
            "active_collection_id": (ctx.get("row") or {}).get("id"),
            "plus_button": tabs,
            "progress": progress,
            "acquisition": acquisition,
            "acquisition_options": {
                "types": ACQUISITION_NAMES,
                "digital_stores": DIGITAL_STORE_NAMES,
                "fields": [
                    "acquisition",
                    "source",
                    "date",
                    "amount",
                    "additional_cost",
                    "notes",
                    "digital_service",
                ],
            },
            "progress_options": {
                "status": list(STATUS_NAMES.items()),
                "completion": list(COMPLETION_NAMES.items()),
                "progress_bar": "0-100, visible when Playing or Played",
                "notes_selector": "#progress-note",
            },
            "rating_api": rating_data,
            "rating_widgets": rating_widgets,
            "rating_card_hidden_until": "Playing or Played (Unplayed and No Status hide .collection-rating)",
            "rating_scale": {
                "export": "1-10",
                "stars": "0.5-5, increment 0.5",
                "labels": RATING_SCORE_LABELS,
                "subratings": ["Overall Rating", "Visual", "Gameplay", "Story", "Audio", "Playability"],
            },
            "reviews_published": _reviews_list(published.get("data")),
            "reviews_drafts": _reviews_list(drafts.get("data")) if drafts.get("ok") else {"error": drafts},
            "review_form": {
                "path": f"/games/{ctx['slug']}/add-review",
                "min_publish_chars": REVIEW_MIN_PUBLISH_CHARS,
                "options": [
                    "spoilers",
                    "mature content",
                    "title",
                    "body",
                    "the good",
                    "the bad",
                    "post feed",
                    "language",
                    "platform",
                    "edition",
                    "completion",
                    "playtime",
                    "save draft",
                    "publish",
                ],
            },
            "delete_button": {
                "labels": (acquisition or {}).get("delete_buttons") if isinstance(acquisition, dict) else None,
                "copy_delete": "DELETE GAME",
                "confirm_heading": "DELETE GAME FROM COLLECTION",
                "confirm_buttons": ["YES", "NO"],
                "do_not_click": True,
                "hint": "Only delete_game_copy with confirm=true clicks the single DELETE GAME FOR {platform} button, then YES.",
            },
            "play_records": {
                "tab": (acquisition or {}).get("play_records_tab") if isinstance(acquisition, dict) else None,
                "path": f"/users/{ctx['username']}/collection/{ctx['slug']}/edit/stats",
                "types": list(PLAY_RECORD_TYPES),
            },
            "custom_tags": {
                "present": bool((acquisition or {}).get("custom_tags")) if isinstance(acquisition, dict) else False,
                "unlock_required": bool((acquisition or {}).get("unlock_custom_tags")) if isinstance(acquisition, dict) else False,
                "profile_scope": "UNLOCK CUSTOM TAGS is a profile/patron feature. Do not click it.",
            },
            "view": view,
            "edit": edit,
        }
    )

async def add_game_platform_copy(
    slug: str,
    platform: str = "",
    digital: bool | None = None,
    collection_id: str = "",
    submit: bool = True,
    wait_ms: int = 3000,
) -> str:
    """Add another GAME INFORMATION copy via button.extra-platform on the collection edit header. Skips if that platform copy already exists. Never fills Acquisition Info. Never DELETE GAME. Pass submit=false to fill the form without saving. Platform is taken from the caller, or inferred when the extra-copy select has exactly one real option. Digital/Physical is changed only when digital is passed."""
    page = await _ensure_browser()
    ctx = await _resolve_game_context(page, slug, collection_id, wait_ms)
    if not ctx.get("rows"):
        return _dumps({"error": "no_collection_row", "slug": ctx.get("slug")})
    if len(ctx["rows"]) > 1 and not str(collection_id).strip() and not (ctx.get("row") or {}).get("id"):
        return _dumps(
            {
                "error": "collection_id_required",
                "parent_rows": [r.get("id") for r in ctx["rows"]],
            }
        )

    wanted = normalize_platform_alias(platform)
    cid = str((ctx.get("row") or {}).get("id") or collection_id or "")
    edit = await _open_collection_edit(page, ctx["username"], ctx["slug"], cid, wait_ms)
    if edit.get("error"):
        return _dumps(edit)
    tabs = await page.evaluate(SNAPSHOT_PLATFORM_TABS_JS)
    tabs_guess = [t.get("text") for t in (tabs or {}).get("copies_tabs") or []]
    if wanted:
        wanted_l = wanted.lower()
        if any(wanted_l == (t or "").lower() or wanted_l in (t or "").lower() or (t or "").lower() in wanted_l for t in tabs_guess):
            return _dumps(
                {
                    "status": "already_has_platform",
                    "platform": wanted,
                    "tabs": tabs,
                    "copies": [slim_collection_row(r) for r in ctx["rows"]],
                }
            )

    plus = await page.evaluate(
        """() => {
          const btn = document.querySelector('button.extra-platform');
          if (!btn) return { clicked: false };
          btn.click();
          return { clicked: true };
        }"""
    )
    await page.wait_for_timeout(max(1200, wait_ms // 2))
    options = await page.evaluate(LIST_PLATFORM_OPTIONS_JS)
    if not wanted:
        real = [o for o in (options or []) if str(o).strip()]
        if len(real) == 1:
            wanted = real[0]
        else:
            return _dumps(
                {
                    "error": "platform_required",
                    "hint": "Pass platform, or add a copy when the extra-copy select has exactly one option.",
                    "options": real,
                    "plus": plus,
                    "url": page.url,
                }
            )

    fill = await page.evaluate(FILL_PLATFORM_COPY_JS, {"platformText": wanted, "digital": digital})
    click = {"clicked": False, "skipped": "submit_false"}
    if submit:
        click = await page.evaluate(
            CLICK_NAMED_BUTTON_JS,
            {"names": ["ADD TO COLLECTION", "ADD GAME", "UPDATE GAME"], "forbid": "DELETE"},
        )
        await page.wait_for_timeout(2500)

    after_rows = await _collection_rows_for_game(page, ctx["user_id"], ctx["game_id"] or 0)
    return _dumps(
        {
            "slug": ctx["slug"],
            "game_id": ctx["game_id"],
            "plus": plus,
            "fill": fill,
            "submit": submit,
            "click": click,
            "copies_before": [slim_collection_row(r) for r in ctx["rows"]],
            "copies_after": [slim_collection_row(r) for r in after_rows],
            "url": page.url,
        }
    )

async def set_game_progress(
    slug: str,
    collection_id: str = "",
    status: str = "",
    completion: str = "",
    progress: str = "",
    notes: str = "",
    clear_fields: str = "",
    wait_ms: int = 3000,
) -> str:
    """Set per-copy progress on the collection edit form: status, completion, 0-100 bar, progress notes. collection_id required when multiple copies exist. Changes only provided fields. clear_fields JSON list can empty notes/progress/status. One UPDATE GAME. Does not touch edition, DLC, Digital Service, or Acquisition Info. Never DELETE GAME."""
    status_id = normalize_status(status) if status else None
    completion_id = normalize_completion(completion) if completion else None
    if status and status_id is None:
        return _dumps({"error": "unknown_status", "status": status, "allowed": STATUS_NAMES})
    if completion and completion_id is None:
        return _dumps({"error": "unknown_completion", "completion": completion, "allowed": COMPLETION_NAMES})
    try:
        pct = parse_progress_pct(progress)
    except ValueError:
        return _dumps({"error": "invalid_progress", "progress": progress})
    notes_arg: str | None = notes if notes != "" else None
    for field in parse_clear_fields(clear_fields):
        key = _alias_key(field)
        if key in ("notes", "progress notes"):
            notes_arg = ""
        elif key in ("progress", "bar", "manual progress"):
            pct = 0
        elif key in ("status",):
            status_id = "unplayed"
        elif key in ("completion",):
            completion_id = "notStarted"
    if status_id is None and completion_id is None and pct is None and notes_arg is None:
        return _dumps({"error": "no_fields", "hint": "Pass status, completion, progress, notes, and/or clear_fields."})

    page = await _ensure_browser()
    ctx = await _resolve_game_context(page, slug, collection_id, wait_ms)
    if not ctx.get("rows"):
        return _dumps({"error": "no_collection_row", "slug": ctx.get("slug")})
    if len(ctx["rows"]) > 1 and not str(collection_id).strip():
        return _dumps(
            {
                "error": "collection_id_required",
                "hint": "Parent has more than one collection row. Pass collection_id.",
                "parent_rows": [slim_collection_row(r) for r in ctx["rows"]],
            }
        )
    cid = str((ctx.get("row") or {}).get("id") or collection_id or "")
    edit = await _open_collection_edit(page, ctx["username"], ctx["slug"], cid, wait_ms)
    if edit.get("error"):
        return _dumps(edit)

    before = slim_collection_row(ctx.get("row"))
    snapshot_before = await page.evaluate(SNAPSHOT_PROGRESS_JS)
    form = await page.evaluate(
        SET_PROGRESS_FORM_JS,
        {"statusId": status_id, "completionId": None, "notes": None, "progress": None},
    )
    await page.wait_for_timeout(600)
    form2 = await page.evaluate(
        SET_PROGRESS_FORM_JS,
        {"statusId": None, "completionId": completion_id, "notes": notes_arg, "progress": pct},
    )
    snapshot_mid = await page.evaluate(SNAPSHOT_PROGRESS_JS)
    update = await _click_update_game(page)
    if cid:
        await _wait_left_edit_form(page, cid)

    after_rows = await _collection_rows_for_game(page, ctx["user_id"], ctx["game_id"] or 0)
    after = None
    for r in after_rows:
        if str(r.get("id")) == cid:
            after = r
            break
    return _dumps(
        {
            "slug": ctx["slug"],
            "collection_id": cid,
            "before": before,
            "form": {"first": form, "second": form2},
            "snapshot_before": snapshot_before,
            "snapshot_before_update": snapshot_mid,
            "update": update,
            "after": slim_collection_row(after),
        }
    )

async def set_game_acquisition(
    slug: str,
    collection_id: str = "",
    acquisition: str = "",
    source: str = "",
    date: str = "",
    amount: str = "",
    additional_cost: str = "",
    notes: str = "",
    digital_service: str = "",
    subscription: str = "",
    clear_fields: str = "",
    wait_ms: int = 3000,
) -> str:
    """Set or clear ACQUISITION INFO on a collection copy. Only provided fields change. clear_fields is a JSON list (source, amount, date, notes, acquisition, digital_service, additional_cost). One UPDATE GAME. collection_id required when multiple copies exist. Never DELETE GAME. Never UNLOCK CUSTOM TAGS."""
    clears = {_alias_key(x) for x in parse_clear_fields(clear_fields)}
    acq_id = None
    if "acquisition" in clears:
        acq_id = ""
    elif acquisition.strip():
        acq_id = normalize_acquisition(acquisition)
        if acq_id is None:
            return _dumps({"error": "unknown_acquisition", "acquisition": acquisition, "allowed": ACQUISITION_NAMES})
    store_id = None
    if "digital service" in clears or "digital_store" in clears or "digitalstore" in clears:
        store_id = ""
    elif digital_service.strip():
        store_id = normalize_digital_store(digital_service)
        if store_id is None:
            return _dumps({"error": "unknown_digital_service", "digital_service": digital_service, "allowed": DIGITAL_STORE_NAMES})

    payload: dict[str, Any] = {}
    if acq_id is not None:
        payload["acquisition"] = acq_id
    if store_id is not None:
        payload["digitalService"] = store_id
    if "source" in clears:
        payload["source"] = ""
    elif source != "":
        payload["source"] = source
    if "date" in clears:
        payload["date"] = ""
    elif date != "":
        payload["date"] = date
    if "amount" in clears:
        payload["amount"] = ""
    elif amount != "":
        text = amount.strip()
        if re.fullmatch(r"-?\d+(\.\d+)?", text):
            num = float(text)
            payload["amount"] = int(num) if num.is_integer() else num
        else:
            payload["amount"] = amount
    if "additional cost" in clears or "additional_cost" in clears or "additionalcost" in clears:
        payload["additionalCost"] = ""
    elif additional_cost != "":
        payload["additionalCost"] = additional_cost
    if "notes" in clears or "acquisition notes" in clears:
        payload["notes"] = ""
    elif notes != "":
        payload["notes"] = notes
    if subscription != "":
        payload["subscription"] = subscription
    if not payload:
        return _dumps({"error": "no_fields", "hint": "Pass acquisition/source/date/amount/notes/digital_service or clear_fields."})

    page = await _ensure_browser()
    ctx = await _resolve_game_context(page, slug, collection_id, wait_ms)
    if not ctx.get("rows"):
        return _dumps({"error": "no_collection_row", "slug": ctx.get("slug")})
    blocked = _require_collection_id(ctx, collection_id)
    if blocked:
        return _dumps(blocked)
    cid = str((ctx.get("row") or {}).get("id") or collection_id or "")
    edit = await _open_collection_edit(page, ctx["username"], ctx["slug"], cid, wait_ms)
    if edit.get("error"):
        return _dumps(edit)
    before = slim_collection_row(ctx.get("row"))
    snap_before = await page.evaluate(SNAPSHOT_ACQUISITION_JS)
    form = await page.evaluate(SET_ACQUISITION_FORM_JS, payload)
    snapshot_mid = await page.evaluate(SNAPSHOT_ACQUISITION_JS)
    update = await _click_update_game(page)
    if cid:
        await _wait_left_edit_form(page, cid)
    after_rows = await _collection_rows_for_game(page, ctx["user_id"], ctx["game_id"] or 0)
    after = None
    for r in after_rows:
        if str(r.get("id")) == cid:
            after = r
            break
    return _dumps(
        {
            "slug": ctx["slug"],
            "collection_id": cid,
            "before": before,
            "form": form,
            "snapshot_before": snap_before,
            "snapshot_before_update": snapshot_mid,
            "update": update,
            "after": slim_collection_row(after),
        }
    )

async def delete_game_copy(
    slug: str,
    collection_id: str,
    confirm: bool = False,
    wait_ms: int = 3000,
) -> str:
    """Delete a saved collection copy. collection_id always required. confirm=true required. On the saved edit form, clicks the single DELETE GAME FOR {platform} button, then YES. Does not click when that button is missing or duplicated, and does not click DELETE DRAFT. Last remaining copy removes the game from the collection."""
    if not str(collection_id or "").strip():
        return _dumps({"error": "collection_id_required", "hint": "collection_id is always required to delete a copy."})
    if not confirm:
        return _dumps(
            {
                "error": "confirm_required",
                "hint": "Pass confirm=true to click DELETE GAME. Last copy removes the game from the collection.",
                "collection_id": collection_id,
            }
        )
    page = await _ensure_browser()
    ctx = await _resolve_game_context(page, slug, collection_id, wait_ms)
    if not ctx.get("rows"):
        return _dumps({"error": "no_collection_row", "slug": ctx.get("slug")})
    cid = str(collection_id).strip()
    if not any(str(r.get("id")) == cid for r in ctx["rows"]):
        return _dumps({"error": "collection_id_not_found", "collection_id": cid, "rows": [r.get("id") for r in ctx["rows"]]})
    edit = await _open_collection_edit(page, ctx["username"], ctx["slug"], cid, wait_ms)
    if edit.get("error"):
        return _dumps(edit)
    if f"id={cid}" not in (page.url or ""):
        return _dumps({"error": "wrong_edit_url", "url": page.url, "collection_id": cid})
    found = await page.evaluate(
        """() => {
          const hasUpdate = [...document.querySelectorAll('button')].some(b => (b.innerText || '').trim() === 'UPDATE GAME');
          const labels = [...document.querySelectorAll('button')].map(b => (b.innerText || '').trim()).filter(t => t.startsWith('DELETE GAME FOR '));
          return { hasUpdate, labels };
        }"""
    )
    label = saved_delete_label((found or {}).get("labels")) if (found or {}).get("hasUpdate") else None
    if not label:
        return _dumps({"error": "delete_button_missing", "url": page.url, "found": found})
    click = await _click_exact_button(page, label)
    if not click.get("clicked"):
        return _dumps({"error": "delete_button_missing", "url": page.url, "click": click, "label": label})
    await page.wait_for_timeout(800)
    modal = await page.evaluate(
        """() => {
          const heading = [...document.querySelectorAll('h1,h2,h3,h4,h5')].map(e => (e.innerText || '').trim()).find(t => /DELETE GAME FROM COLLECTION/i.test(t)) || '';
          const buttons = [...document.querySelectorAll('button')].map(b => (b.innerText || '').trim()).filter(t => /^(YES|NO)$/i.test(t));
          return { heading, buttons, hint: 'Are you sure you want to delete this game from your collection?' };
        }"""
    )
    if "DELETE GAME FROM COLLECTION" not in (modal.get("heading") or "").upper():
        return _dumps({"error": "confirm_modal_missing", "url": page.url, "click": click, "modal": modal})
    confirm_click = await _click_exact_button(page, "YES")
    await page.wait_for_timeout(2500)
    after_rows = await _collection_rows_for_game(page, ctx["user_id"], ctx["game_id"] or 0)
    still = any(str(r.get("id")) == cid for r in after_rows)
    return _dumps(
        {
            "slug": ctx["slug"],
            "collection_id": cid,
            "click": click,
            "modal": modal,
            "confirm": confirm_click,
            "removed": not still,
            "copies_after": [slim_collection_row(r) for r in after_rows],
            "url": page.url,
        }
    )


def register(mcp) -> None:
    mcp.tool()(locked_tool(list_collection_game_options))
    mcp.tool()(locked_tool(add_game_platform_copy))
    mcp.tool()(locked_tool(set_game_progress))
    mcp.tool()(locked_tool(set_game_acquisition))
    mcp.tool()(locked_tool(delete_game_copy))
