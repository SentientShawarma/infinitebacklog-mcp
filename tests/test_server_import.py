"""Smoke tests that load the MCP server without launching a browser."""
from __future__ import annotations

import os
import unittest

os.environ["IB_CDP"] = "0"


class ServerImportTests(unittest.TestCase):
    def test_import_server_without_browser(self) -> None:
        from infinitebacklog_mcp.server import main, mcp

        self.assertTrue(callable(main))
        self.assertEqual(mcp.name, "infinitebacklog")
        self.assertEqual(mcp.version, "1.0.1")

    def test_registered_tools(self) -> None:
        from infinitebacklog_mcp.server import mcp

        tools = mcp._tool_manager._tools
        expected = {
            "open_site",
            "get_page_text",
            "get_page_html",
            "search_games",
            "click",
            "fill",
            "screenshot",
            "evaluate_js",
            "get_links",
            "current_url",
            "login",
            "close_browser",
            "list_related_content",
            "list_collection_content_menus",
            "add_game_content",
            "list_collection_game_options",
            "set_game_rating",
            "add_game_review",
            "delete_game_review",
            "add_game_platform_copy",
            "set_game_progress",
            "set_game_acquisition",
            "delete_game_copy",
            "list_play_records",
            "set_play_record_category",
            "set_play_record",
            "remove_play_record",
            "run_browser_use_task",
        }
        self.assertEqual(set(tools), expected)


if __name__ == "__main__":
    unittest.main()
