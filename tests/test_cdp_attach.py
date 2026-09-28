"""Unit tests for local-browser attach. They do not open a browser."""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

os.environ["IB_CDP"] = "0"

from infinitebacklog_mcp import browser as browser_mod
from infinitebacklog_mcp.cdp_bridge import (
    CdpOriginBridge,
    _IbTargetGate,
    _encode_frame,
    _rewrite_auto_attach,
    _split_frames,
)
from infinitebacklog_mcp.cdp_attach import (
    debug_json_urls,
    discover_endpoint_urls,
    parse_devtools_active_port,
    pick_ib_target,
    websocket_url_from_version,
)


class DebugJsonUrlTests(unittest.TestCase):
    def test_version_and_list_use_the_json_prefix(self) -> None:
        self.assertEqual(
            debug_json_urls("http://127.0.0.1:9222", "version"),
            [
                "http://127.0.0.1:9222/json/version",
                "http://127.0.0.1:9222/json/version/",
            ],
        )
        self.assertEqual(
            debug_json_urls("http://127.0.0.1:9222/", "list"),
            [
                "http://127.0.0.1:9222/json/list",
                "http://127.0.0.1:9222/json/list/",
            ],
        )


class PortFileTests(unittest.TestCase):
    def test_parses_port_and_ignores_the_path_line(self) -> None:
        self.assertEqual(parse_devtools_active_port("9222\n/devtools/browser/abc\n"), 9222)

    def test_rejects_blank_and_non_numeric(self) -> None:
        self.assertIsNone(parse_devtools_active_port(""))
        self.assertIsNone(parse_devtools_active_port("nope"))
        self.assertIsNone(parse_devtools_active_port("0"))
        self.assertIsNone(parse_devtools_active_port("70000"))


class DiscoverTests(unittest.TestCase):
    def test_env_url_is_exclusive(self) -> None:
        brave = Path("BraveSoftware/Brave-Browser/User Data/DevToolsActivePort")
        urls = discover_endpoint_urls(
            env_url="http://127.0.0.1:9333",
            port_files=[brave],
            include_probe=True,
        )
        self.assertEqual(urls, [("env", "http://127.0.0.1:9333", None)])

    def test_remote_env_url_is_dropped(self) -> None:
        urls = discover_endpoint_urls(
            env_url="http://evil.example:9222",
            port_files=[],
            include_probe=True,
        )
        self.assertEqual(urls, [("probe", "http://127.0.0.1:9222", None)])

    def test_port_file_then_probe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            brave = Path(tmp) / "BraveSoftware" / "Brave-Browser" / "User Data" / "DevToolsActivePort"
            brave.parent.mkdir(parents=True, exist_ok=True)
            brave.write_text("9334\n/devtools/browser/abc\n", encoding="utf-8")
            urls = discover_endpoint_urls(env_url="", port_files=[brave], include_probe=True)
        self.assertEqual(
            urls,
            [
                ("brave", "http://127.0.0.1:9334", "ws://127.0.0.1:9334/devtools/browser/abc"),
                ("probe", "http://127.0.0.1:9222", None),
            ],
        )

    def test_websocket_must_be_local(self) -> None:
        self.assertIsNone(websocket_url_from_version({"webSocketDebuggerUrl": "ws://evil.example/devtools"}))
        self.assertEqual(
            websocket_url_from_version({"webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/browser/abc"}),
            "ws://127.0.0.1:9222/devtools/browser/abc",
        )


class PickTargetTests(unittest.TestCase):
    def test_prefers_collection_tab_and_ignores_other_sites(self) -> None:
        chosen = pick_ib_target(
            [
                {"type": "page", "url": "https://example.com/"},
                {"type": "page", "url": "https://infinitebacklog.net/games"},
                {"type": "service_worker", "url": "https://infinitebacklog.net/sw.js"},
                {"type": "page", "url": "https://infinitebacklog.net/users/ada/collection"},
            ]
        )
        self.assertIsNotNone(chosen)
        assert chosen is not None
        self.assertEqual(chosen["url"], "https://infinitebacklog.net/users/ada/collection")

    def test_none_when_no_ib_page(self) -> None:
        self.assertIsNone(pick_ib_target([{"type": "page", "url": "https://example.com"}]))
        self.assertIsNone(pick_ib_target(None))


class FrameRewriteTests(unittest.TestCase):
    def test_auto_attach_does_not_pause_the_browser(self) -> None:
        payload = (
            b'{"id":2,"method":"Target.setAutoAttach","params":'
            b'{"autoAttach":true,"waitForDebuggerOnStart":true,"flatten":true}}'
        )
        frame = _encode_frame(0x81, payload, b"abcd")
        frames, complete = _split_frames(_rewrite_auto_attach(frame))
        self.assertTrue(complete)
        data = json.loads(frames[0][1])
        self.assertTrue(data["params"]["autoAttach"])
        self.assertFalse(data["params"]["waitForDebuggerOnStart"])
        self.assertEqual(data["id"], 2)


def _attach_event(url: str, kind: str = "page") -> bytes:
    payload = json.dumps(
        {
            "method": "Target.attachedToTarget",
            "params": {
                "sessionId": "abc",
                "targetInfo": {"targetId": "t1", "type": kind, "url": url},
            },
        },
        separators=(",", ":"),
    ).encode("utf-8")
    return _encode_frame(0x81, payload, None)


class TargetGateTests(unittest.TestCase):
    def test_only_infinite_backlog_pages_are_forwarded(self) -> None:
        gate = _IbTargetGate()
        other = gate.feed(_attach_event("https://example.com/"))
        self.assertEqual(other, b"")
        kept = gate.feed(_attach_event("https://infinitebacklog.net/users/demo"))
        frames, complete = _split_frames(kept)
        self.assertTrue(complete)
        data = json.loads(frames[0][1])
        self.assertEqual(data["params"]["targetInfo"]["url"], "https://infinitebacklog.net/users/demo")

    def test_split_frame_is_held_until_complete(self) -> None:
        frame = _attach_event("https://example.com/")
        gate = _IbTargetGate()
        self.assertEqual(gate.feed(frame[:5]), b"")
        self.assertEqual(gate.feed(frame[5:]), b"")


class BridgeTests(unittest.TestCase):
    def test_bridge_strips_origin_and_hides_browser_id(self) -> None:
        asyncio.run(self._bridge())

    async def _bridge(self) -> None:
        seen: dict[str, str] = {}

        async def upstream(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            buf = b""
            while b"\r\n\r\n" not in buf:
                chunk = await reader.read(4096)
                if not chunk:
                    return
                buf += chunk
            header = buf.split(b"\r\n\r\n", 1)[0].decode("latin1")
            seen["header"] = header
            if "\norigin:" in header.lower():
                writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                await writer.drain()
                writer.close()
                return
            writer.write(
                b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n"
            )
            await writer.drain()
            await asyncio.sleep(0.2)
            writer.close()

        server = await asyncio.start_server(upstream, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        bridge = CdpOriginBridge(f"ws://127.0.0.1:{port}/devtools/browser/secret-token")
        await bridge.start()
        try:
            bport = int(bridge.http_url.rsplit(":", 1)[1])
            reader, writer = await asyncio.open_connection("127.0.0.1", bport)
            writer.write(b"GET /json/version/ HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
            await writer.drain()
            body = await asyncio.wait_for(reader.read(4096), timeout=2)
            writer.close()
            self.assertIn(b"/devtools/browser/proxy", body)
            self.assertNotIn(b"secret-token", body)

            reader, writer = await asyncio.open_connection("127.0.0.1", bport)
            writer.write(
                b"GET /devtools/browser/proxy HTTP/1.1\r\n"
                b"Host: 127.0.0.1\r\n"
                b"Upgrade: websocket\r\n"
                b"Connection: Upgrade\r\n"
                b"Origin: http://127.0.0.1:9\r\n"
                b"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
                b"Sec-WebSocket-Version: 13\r\n"
                b"\r\n"
            )
            await writer.drain()
            hello = await asyncio.wait_for(reader.read(256), timeout=3)
            self.assertIn(b"101", hello)
            writer.close()
        finally:
            await bridge.stop()
            server.close()
            await server.wait_closed()
        self.assertNotIn("\norigin:", seen["header"].lower())


class CloseTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._saved = (
            browser_mod._browser,
            browser_mod._context,
            browser_mod._page,
            browser_mod._playwright,
            browser_mod._headless_mode,
            browser_mod._attached,
            browser_mod._opened_page,
            browser_mod._attach_source,
        )

    def tearDown(self) -> None:
        (
            browser_mod._browser,
            browser_mod._context,
            browser_mod._page,
            browser_mod._playwright,
            browser_mod._headless_mode,
            browser_mod._attached,
            browser_mod._opened_page,
            browser_mod._attach_source,
        ) = self._saved

    def _install(self, *, attached: bool, opened: bool):
        page = MagicMock()
        page.is_closed.return_value = False
        page.close = AsyncMock()
        context = MagicMock()
        context.close = AsyncMock()
        browser = MagicMock()
        browser.close = AsyncMock()
        playwright = MagicMock()
        playwright.stop = AsyncMock()
        browser_mod._page = page
        browser_mod._context = context
        browser_mod._browser = browser
        browser_mod._playwright = playwright
        browser_mod._attached = attached
        browser_mod._opened_page = opened
        browser_mod._attach_source = "brave" if attached else ""
        browser_mod._headless_mode = False
        return page, context, browser, playwright

    async def test_attached_close_leaves_user_tab_and_context(self) -> None:
        page, context, browser, playwright = self._install(attached=True, opened=False)
        await browser_mod._close_browser()
        page.close.assert_not_called()
        context.close.assert_not_called()
        browser.close.assert_awaited()
        playwright.stop.assert_awaited()
        self.assertFalse(browser_mod._attached)
        self.assertIsNone(browser_mod._browser)

    async def test_attached_close_closes_only_a_tab_this_server_opened(self) -> None:
        page, context, browser, _playwright = self._install(attached=True, opened=True)
        await browser_mod._close_browser()
        page.close.assert_awaited()
        context.close.assert_not_called()
        browser.close.assert_awaited()

    async def test_launched_close_closes_context(self) -> None:
        page, context, browser, _playwright = self._install(attached=False, opened=True)
        await browser_mod._close_browser()
        page.close.assert_awaited()
        context.close.assert_awaited()
        browser.close.assert_awaited()


if __name__ == "__main__":
    unittest.main()
