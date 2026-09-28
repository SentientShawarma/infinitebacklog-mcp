import json
import unittest

from infinitebacklog_mcp.matching import (
    _find_addition,
    _game_id_from_hit,
    _kind_from_label,
    _match_item,
    _names_match,
    _normalize_name,
    _owned_title_hit,
)


PARENT = "Tomb Raider"


class NormalizeTests(unittest.TestCase):
    def test_reticle_to_reticule(self):
        self.assertEqual(
            _normalize_name("Headshot Reticle", PARENT),
            _normalize_name("Tomb Raider: Headshot Reticule", PARENT),
        )

    def test_strips_parent_and_skin(self):
        self.assertEqual(_normalize_name("Tomb Raider: Aviatrix Skin", PARENT), "aviatrix")
        self.assertEqual(_normalize_name("Hunter Skin", PARENT), "hunter")

    def test_names_match_agility(self):
        self.assertTrue(_names_match("Agility", "Tomb Raider: Agility Skill", PARENT))


class KindTests(unittest.TestCase):
    def test_pack_addon_label(self):
        self.assertEqual(_kind_from_label("PACK/ADDON"), "pack_addon")

    def test_dlc_tab(self):
        self.assertEqual(_kind_from_label("DLC (23)"), "dlc")

    def test_edition_card(self):
        self.assertEqual(_kind_from_label("EDITION"), "edition")


class MatchTests(unittest.TestCase):
    def setUp(self):
        self.related = [
            {
                "title": "Tomb Raider: Agility Skill",
                "slug": "tomb-raider-agility-skill",
                "kind": "dlc",
                "section": "DLC (23)",
                "section_kind": "dlc",
            },
            {
                "title": "Tomb Raider: Aviatrix Skin",
                "slug": "tomb-raider-aviatrix-skin",
                "kind": "pack_addon",
                "section": "DLC (23)",
                "section_kind": "dlc",
            },
            {
                "title": "Tomb Raider: Survival Edition",
                "slug": "tomb-raider-survival-edition",
                "kind": "edition",
                "section": "EDITIONS (3)",
                "section_kind": "edition",
            },
        ]
        self.menus = {
            "selects": [
                {
                    "label": "",
                    "kind": "dlc",
                    "role": "add_dlc",
                    "options": [
                        {"text": "Add DLC to your game", "value": "", "selected": True},
                        {
                            "text": "Tomb Raider: Agility Skill",
                            "value": "406527",
                            "game_id": 406527,
                            "selected": False,
                        },
                    ],
                }
            ],
            "checkboxes": [
                {
                    "id": "addon-406530",
                    "label": "Tomb Raider: Aviatrix Skin",
                    "kind": "pack_addon",
                    "game_id": 406530,
                    "checked": False,
                }
            ],
        }

    def test_prefers_dlc_then_pack(self):
        agility = _match_item("Agility", self.related, self.menus, PARENT, "dlc")
        self.assertEqual(agility["kind"], "dlc")
        self.assertEqual(agility["_matched_in"], "dlc")
        aviatrix = _match_item("Aviatrix", self.related, self.menus, PARENT, "dlc")
        self.assertEqual(aviatrix["kind"], "pack_addon")
        self.assertEqual(aviatrix["_matched_in"], "pack_addon")

    def test_skips_placeholder_option(self):
        hit = _match_item("Add DLC to your game", [], self.menus, PARENT, None)
        self.assertIsNone(hit)

    def test_edition_only_match(self):
        hit = _match_item("Survival Edition Bonus Content", self.related, self.menus, PARENT, "edition")
        self.assertEqual(hit["kind"], "edition")

    def test_japanese_pack_not_found(self):
        hit = _match_item("Japanese Language Pack", self.related, self.menus, PARENT, "dlc")
        if hit is None:
            hit = _match_item("Japanese Language Pack", self.related, self.menus, PARENT, None)
        self.assertIsNone(hit)


class AdditionTests(unittest.TestCase):
    def test_owned_is_parent_addition_not_standalone_row(self):
        additions = [
            {
                "id": 250903,
                "game_id": 144991,
                "game": {
                    "id": 144991,
                    "name": "Tomb Raider: Tomb of the Lost Adventurer",
                    "slug": "tomb-raider-tomb-of-the-lost-adventurer",
                },
            }
        ]
        hit = _find_addition("Tomb of the Lost Adventurer", PARENT, additions)
        self.assertEqual(hit["id"], 250903)
        self.assertIsNone(_find_addition("Agility", PARENT, additions, 406527))

    def test_game_id_from_addon_id(self):
        self.assertEqual(_game_id_from_hit({"id": "addon-406530"}), 406530)
        self.assertEqual(_game_id_from_hit({"value": "406527"}), 406527)

    def test_owned_dlc_titles(self):
        titles = ["Tomb Raider: Shanty Town", "Tomb Raider: Agility Skill"]
        self.assertEqual(_owned_title_hit("Shanty Town", PARENT, titles), "Tomb Raider: Shanty Town")
        self.assertIsNone(_owned_title_hit("Japanese Language Pack", PARENT, titles))


class RatingProgressEnumTests(unittest.TestCase):
    def test_score_labels(self):
        from infinitebacklog_mcp.normalize import rating_label

        self.assertEqual(rating_label(10), "Masterpiece")
        self.assertEqual(rating_label(5), "Mediocre")
        self.assertEqual(rating_label(1), "Disaster")

    def test_score_to_star_event(self):
        from infinitebacklog_mcp.normalize import score_to_star_event

        ten = score_to_star_event(10)
        self.assertEqual(ten["id"], 5)
        self.assertEqual(ten["position"], 100)
        five = score_to_star_event(5)
        self.assertEqual(five["id"], 3)
        self.assertEqual(five["position"], 50)
        one = score_to_star_event(1)
        self.assertEqual(one["id"], 1)
        self.assertEqual(one["position"], 50)

    def test_status_aliases(self):
        from infinitebacklog_mcp.normalize import normalize_status

        self.assertEqual(normalize_status("Played"), "played")
        self.assertEqual(normalize_status("No Status"), "noStatus")
        self.assertEqual(normalize_status("playing"), "playing")

    def test_completion_aliases(self):
        from infinitebacklog_mcp.normalize import normalize_completion

        self.assertEqual(normalize_completion("Beaten"), "campaignCompleted")
        self.assertEqual(normalize_completion("campaignCompleted"), "campaignCompleted")
        self.assertEqual(normalize_completion("Not Started"), "notStarted")
        self.assertEqual(normalize_completion("Dropped"), "dropped")

    def test_playability_maps_to_accessibility(self):
        from infinitebacklog_mcp.config import RATING_API_FIELDS, RATING_WIDGET_LABELS

        self.assertEqual(RATING_API_FIELDS["playability"], "accessibility")
        self.assertEqual(RATING_WIDGET_LABELS["playability"], "Playability")
        self.assertEqual(RATING_WIDGET_LABELS["accessibility"], "Playability")


class AcquisitionPlayRecordTests(unittest.TestCase):
    def test_acquisition_aliases(self):
        from infinitebacklog_mcp.normalize import normalize_acquisition

        self.assertEqual(normalize_acquisition("Purchase"), "purchase")
        self.assertEqual(normalize_acquisition("Gifted"), "gift")
        self.assertEqual(normalize_acquisition("key bundle"), "keyBundle")
        self.assertEqual(normalize_acquisition("Free-to-play"), "freeToPlay")

    def test_digital_store_aliases(self):
        from infinitebacklog_mcp.normalize import normalize_digital_store

        self.assertEqual(normalize_digital_store("Steam"), "steam")
        self.assertEqual(normalize_digital_store("Epic Games"), "epicGameStore")
        self.assertEqual(normalize_digital_store("GOG"), "gog")

    def test_clear_fields_json_list(self):
        from infinitebacklog_mcp.normalize import parse_clear_fields

        self.assertEqual(parse_clear_fields('["source","amount"]'), ["source", "amount"])
        self.assertEqual(parse_clear_fields("notes,date"), ["notes", "date"])

    def test_play_record_types(self):
        from infinitebacklog_mcp.normalize import normalize_play_record_type

        self.assertEqual(normalize_play_record_type("Key-Value Pair"), "keyValue")
        self.assertEqual(normalize_play_record_type("checkbox"), "checkbox")
        self.assertEqual(normalize_play_record_type("table"), "table")

    def test_clear_fields_empty(self):
        from infinitebacklog_mcp.normalize import parse_clear_fields

        self.assertEqual(parse_clear_fields(""), [])

    def test_profile_scope_shape(self):
        from infinitebacklog_mcp.normalize import profile_scope

        out = profile_scope("global_category", "MCP probe")
        self.assertEqual(out["error"], "profile_scope")
        self.assertIn("profile", out["hint"].lower())
        self.assertEqual(out["detail"], "MCP probe")

    def test_play_record_category_profile_scope_without_confirm_new(self):
        from infinitebacklog_mcp.normalize import refuse_global_play_record_category

        blocked = refuse_global_play_record_category(False, "MCP probe", heading="Add global category")
        self.assertEqual(blocked["error"], "profile_scope")
        allowed = refuse_global_play_record_category(False, "MCP probe", heading="ADD NEW CATEGORY")
        self.assertIsNone(allowed)

    def test_slim_row_includes_acquisition(self):
        from infinitebacklog_mcp.normalize import slim_collection_row

        slim = slim_collection_row(
            {
                "id": 9866217,
                "acquisition": "purchase",
                "digital_store": "steam",
                "purchase_place_name": "MCP probe",
                "purchase_price": "1.00",
                "acquisition_notes": "MCP probe",
                "gameplay_stats_id": None,
            }
        )
        self.assertEqual(slim["acquisition"], "purchase")
        self.assertEqual(slim["purchase_place_name"], "MCP probe")
        self.assertEqual(slim["digital_store"], "steam")


class UserIdSearchTests(unittest.TestCase):
    def test_matches_username_not_first_row(self):
        from infinitebacklog_mcp.pages import user_id_from_search

        rows = [
            {"id": 1, "username": "Adilya"},
            {"id": 34007, "username": "SilverWarden"},
        ]
        self.assertEqual(user_id_from_search("silverwarden", rows), 34007)

    def test_no_match_returns_zero(self):
        from infinitebacklog_mcp.pages import user_id_from_search

        self.assertEqual(user_id_from_search("silverwarden", [{"id": 1, "username": "Adilya"}]), 0)
        self.assertEqual(user_id_from_search("silverwarden", None), 0)


class SavedDeleteLabelTests(unittest.TestCase):
    def test_one_platform_label(self):
        from infinitebacklog_mcp.pages import saved_delete_label

        self.assertEqual(saved_delete_label(["DELETE GAME FOR PS4"]), "DELETE GAME FOR PS4")
        self.assertEqual(saved_delete_label(["UPDATE GAME", "DELETE GAME FOR PC"]), "DELETE GAME FOR PC")

    def test_missing_or_duplicated_label_is_refused(self):
        from infinitebacklog_mcp.pages import saved_delete_label

        self.assertIsNone(saved_delete_label(["DELETE GAME"]))
        self.assertIsNone(saved_delete_label(["DELETE GAME FOR PS4", "DELETE GAME FOR PC"]))
        self.assertIsNone(saved_delete_label(None))


class AddFormAndAddonJsTests(unittest.TestCase):
    def test_add_form_uses_null_select_and_refuses_inexact_platform(self):
        from infinitebacklog_mcp.js import FILL_ADD_FORM_JS

        self.assertIn("null-select", FILL_ADD_FORM_JS)
        self.assertIn("platform_not_exact", FILL_ADD_FORM_JS)

    def test_addon_tick_uses_the_input_and_requires_checked(self):
        from infinitebacklog_mcp.js import TICK_ONE_ADDON_JS

        self.assertIn("c.click()", TICK_ONE_ADDON_JS)
        self.assertIn("HTMLInputElement.prototype, 'checked'", TICK_ONE_ADDON_JS)
        self.assertIn("not_checked", TICK_ONE_ADDON_JS)
        self.assertNotIn("lab.click()", TICK_ONE_ADDON_JS)


class ConfirmGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_delete_copy_requires_confirm(self):
        from infinitebacklog_mcp.tools.collection import delete_game_copy

        out = json.loads(await delete_game_copy("boxes-lost-fragments", "9866217", confirm=False))
        self.assertEqual(out["error"], "confirm_required")

    async def test_delete_copy_requires_collection_id(self):
        from infinitebacklog_mcp.tools.collection import delete_game_copy

        out = json.loads(await delete_game_copy("boxes-lost-fragments", "", confirm=True))
        self.assertEqual(out["error"], "collection_id_required")

    async def test_remove_play_record_requires_confirm(self):
        from infinitebacklog_mcp.tools.play_records import remove_play_record

        out = json.loads(await remove_play_record("boxes-lost-fragments", "MCP probe", confirm=False))
        self.assertEqual(out["error"], "confirm_required")

    async def test_delete_review_requires_confirm(self):
        from infinitebacklog_mcp.tools.reviews import delete_game_review

        out = json.loads(await delete_game_review("boxes-lost-fragments", confirm=False))
        self.assertEqual(out["error"], "confirm_required")

    async def test_delete_published_review_is_profile_scope(self):
        from infinitebacklog_mcp.tools.reviews import delete_game_review

        out = json.loads(await delete_game_review("boxes-lost-fragments", confirm=True, published=True))
        self.assertEqual(out["error"], "profile_scope")


class PlatformAliasTests(unittest.TestCase):
    def test_empty_stays_empty(self):
        from infinitebacklog_mcp.normalize import normalize_platform_alias

        self.assertEqual(normalize_platform_alias(""), "")
        self.assertEqual(normalize_platform_alias("  "), "")

    def test_pc_maps_to_windows_pc(self):
        from infinitebacklog_mcp.normalize import normalize_platform_alias

        self.assertEqual(normalize_platform_alias("PC"), "Windows PC")
        self.assertEqual(normalize_platform_alias("windows"), "Windows PC")

    def test_other_platforms_unchanged(self):
        from infinitebacklog_mcp.normalize import normalize_platform_alias

        self.assertEqual(normalize_platform_alias("PlayStation 5"), "PlayStation 5")


if __name__ == "__main__":
    unittest.main()
