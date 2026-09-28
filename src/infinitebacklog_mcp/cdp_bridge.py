"""Local CDP bridge for browsers that reject a WebSocket Origin header.

Playwright always sends Origin. Brave's inspect-toggle port returns 403 for
that header and accepts the handshake only when Origin is absent. This bridge
listens on 127.0.0.1, answers /json/version for Playwright, and pipes the
socket to the real browser websocket without adding Origin.

The upstream browser id is not included in the URL Playwright sees.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
from urllib.parse import urlparse

from .cdp_attach import is_local_endpoint
from .config import logger
from .security import is_ib_origin

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def _accept_key(client_key: str) -> str:
    digest = hashlib.sha1((client_key + _WS_GUID).encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


class CdpOriginBridge:
    def __init__(self, upstream_ws: str) -> None:
        if not is_local_endpoint(upstream_ws):
            raise ValueError("upstream debug socket must be local")
        parsed = urlparse(upstream_ws)
        if parsed.scheme not in {"ws", "wss"} or not parsed.port or not parsed.path:
            raise ValueError("upstream debug socket must be a ws:// host:port/path")
        self._host = parsed.hostname or "127.0.0.1"
        self._port = parsed.port
        self._path = parsed.path
        self._server: asyncio.AbstractServer | None = None
        self.http_url = ""
        self._clients: set[asyncio.Task] = set()

    async def start(self) -> str:
        self._server = await asyncio.start_server(self._on_client, "127.0.0.1", 0)
        sock = self._server.sockets[0]
        port = sock.getsockname()[1]
        self.http_url = f"http://127.0.0.1:{port}"
        return self.http_url

    async def stop(self) -> None:
        server = self._server
        self._server = None
        tasks = list(self._clients)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if server is not None:
            server.close()
            await server.wait_closed()

    async def _on_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._clients.add(task)
        try:
            await self._handle(reader, writer)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.info("CDP bridge client closed")
        finally:
            if task is not None:
                self._clients.discard(task)
            try:
                writer.close()
            except Exception:
                pass

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        header, rest = await _read_headers(reader)
        if header is None:
            return
        lines = header.decode("latin1", "replace").split("\r\n")
        parts = lines[0].split(" ")
        if len(parts) < 2 or parts[0] != "GET":
            await _write_status(writer, 405, b"")
            return
        path = parts[1].split("?", 1)[0]
        if path.rstrip("/").endswith("/json/version") or path.rstrip("/") == "/json/version":
            body = json.dumps(
                {
                    "Browser": "local-cdp-bridge",
                    "Protocol-Version": "1.3",
                    "webSocketDebuggerUrl": f"ws://127.0.0.1:{urlparse(self.http_url).port}/devtools/browser/proxy",
                }
            ).encode("utf-8")
            await _write_status(writer, 200, body, "application/json")
            return
        if not path.startswith("/devtools/"):
            await _write_status(writer, 404, b"")
            return
        key = ""
        for line in lines[1:]:
            if line.lower().startswith("sec-websocket-key:"):
                key = line.split(":", 1)[1].strip()
        if not key:
            await _write_status(writer, 400, b"")
            return
        try:
            up_reader, up_writer, up_rest = await _open_upstream(self._host, self._port, self._path)
        except Exception as exc:
            logger.info("upstream CDP handshake failed: %s", type(exc).__name__)
            await _write_status(writer, 502, b"")
            return
        accept = _accept_key(key)
        response = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept}\r\n"
            "\r\n"
        )
        writer.write(response.encode("ascii"))
        await writer.drain()
        logger.info("bridge websocket ready leftover=%s upstream_leftover=%s", len(rest), len(up_rest))
        await _pipe(reader, writer, up_reader, up_writer, rest, up_rest)


async def _read_headers(reader: asyncio.StreamReader) -> tuple[bytes | None, bytes]:
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = await reader.read(4096)
        if not chunk:
            return None, b""
        buf += chunk
        if len(buf) > 65536:
            return None, b""
    header, _, rest = buf.partition(b"\r\n\r\n")
    return header, rest


async def _write_status(
    writer: asyncio.StreamWriter,
    status: int,
    body: bytes,
    content_type: str = "text/plain",
) -> None:
    reason = {200: "OK", 400: "Bad Request", 404: "Not Found", 405: "Method Not Allowed", 502: "Bad Gateway"}.get(
        status, "Error"
    )
    head = (
        f"HTTP/1.1 {status} {reason}\r\n"
        f"Content-Type: {content_type}\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Connection: close\r\n"
        "\r\n"
    )
    writer.write(head.encode("ascii") + body)
    await writer.drain()


async def _open_upstream(
    host: str,
    port: int,
    path: str,
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter, bytes]:
    reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=3)
    try:
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        writer.write(request.encode("ascii"))
        await writer.drain()
        header, rest = await asyncio.wait_for(_read_headers(reader), timeout=3)
        status = b"" if header is None else header.split(b"\r\n", 1)[0]
        if b" 101 " not in status:
            logger.info("upstream CDP status: %s", status[:80].decode("latin1", "replace"))
            raise ConnectionError("upstream debug socket rejected the handshake")
        return reader, writer, rest
    except Exception:
        try:
            writer.close()
        except Exception:
            pass
        raise


class _IbTargetGate:
    """Forward attach events only for Infinite Backlog pages.

    Playwright waits until every attached page finishes starting. Other tabs
    in the user's browser are left out of that wait.
    """

    def __init__(self) -> None:
        self._buf = b""
        self._noted: set[str] = set()

    def feed(self, chunk: bytes) -> bytes:
        self._buf += chunk
        frames, self._buf = _take_complete_frames(self._buf)
        if len(self._buf) > 1_000_000:
            extra = self._buf
            self._buf = b""
            return _encode_frames(frames) + extra
        kept: list[tuple[int, bytes, bytes | None]] = []
        for fin_opcode, payload, mask in frames:
            if (fin_opcode & 0x0F) == 1:
                payload_or_drop = self._filter_payload(payload)
                if payload_or_drop is None:
                    continue
                payload = payload_or_drop
            kept.append((fin_opcode, payload, mask))
        return _encode_frames(kept)

    def _filter_payload(self, payload: bytes) -> bytes | None:
        try:
            data = json.loads(payload.decode("utf-8"))
        except Exception:
            return payload
        if not isinstance(data, dict) or data.get("method") != "Target.attachedToTarget":
            return payload
        params = data.get("params")
        info = params.get("targetInfo") if isinstance(params, dict) else None
        if not isinstance(info, dict):
            return payload
        if _keep_attached_target(str(info.get("type") or ""), str(info.get("url") or "")):
            return payload
        kind = str(info.get("type") or "unknown")[:40]
        if kind not in self._noted and len(self._noted) < 8:
            self._noted.add(kind)
            logger.info("bridge skipped non-IB target type=%s", kind)
        return None


def _keep_attached_target(kind: str, url: str) -> bool:
    if kind == "browser":
        return True
    if kind == "page":
        return is_ib_origin(url) or url in {"about:blank", ""}
    if kind in {"service_worker", "shared_worker", "worker"}:
        return is_ib_origin(url)
    return False


def _rewrite_auto_attach(chunk: bytes) -> bytes:
    """Force Target.setAutoAttach to not pause page startup.

    Playwright sends waitForDebuggerOnStart=true and then waits until every
    target attaches. That stalls this browser and the connect call.
    """
    frames, complete = _split_frames(chunk)
    if not complete:
        return chunk
    out = bytearray()
    for fin_opcode, payload, mask in frames:
        if (fin_opcode & 0x0F) == 1:
            payload = _rewrite_auto_attach_payload(payload)
        out += _encode_frame(fin_opcode, payload, mask)
    return bytes(out)


def _rewrite_auto_attach_payload(payload: bytes) -> bytes:
    try:
        data = json.loads(payload.decode("utf-8"))
    except Exception:
        return payload
    if not isinstance(data, dict) or data.get("method") != "Target.setAutoAttach":
        return payload
    params = data.get("params")
    if not isinstance(params, dict):
        params = {}
    params["waitForDebuggerOnStart"] = False
    data["params"] = params
    return json.dumps(data, separators=(",", ":")).encode("utf-8")


def _take_complete_frames(
    buf: bytes,
) -> tuple[list[tuple[int, bytes, bytes | None]], bytes]:
    frames: list[tuple[int, bytes, bytes | None]] = []
    index = 0
    size = len(buf)
    while index + 2 <= size:
        start = index
        fin_opcode = buf[index]
        marker = buf[index + 1]
        masked = bool(marker & 0x80)
        length = marker & 0x7F
        index += 2
        if length == 126:
            if index + 2 > size:
                return frames, buf[start:]
            length = int.from_bytes(buf[index : index + 2], "big")
            index += 2
        elif length == 127:
            if index + 8 > size:
                return frames, buf[start:]
            length = int.from_bytes(buf[index : index + 8], "big")
            index += 8
        mask = None
        if masked:
            if index + 4 > size:
                return frames, buf[start:]
            mask = buf[index : index + 4]
            index += 4
        if index + length > size:
            return frames, buf[start:]
        payload = buf[index : index + length]
        index += length
        if mask:
            payload = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
        frames.append((fin_opcode, payload, mask))
    return frames, buf[index:]


def _split_frames(buf: bytes) -> tuple[list[tuple[int, bytes, bytes | None]], bool]:
    frames, rest = _take_complete_frames(buf)
    if rest:
        return [], False
    return frames, True


def _encode_frames(frames: list[tuple[int, bytes, bytes | None]]) -> bytes:
    out = bytearray()
    for fin_opcode, payload, mask in frames:
        out += _encode_frame(fin_opcode, payload, mask)
    return bytes(out)


def _ws_close(masked: bool) -> bytes:
    """Empty close frame. The browser side of this bridge must mask it."""
    if not masked:
        return bytes((0x88, 0x00))
    mask = os.urandom(4)
    return bytes((0x88, 0x80)) + mask


def _encode_frame(fin_opcode: int, payload: bytes, mask: bytes | None) -> bytes:
    length = len(payload)
    head = bytearray([fin_opcode])
    mask_bit = 0x80 if mask else 0
    if length < 126:
        head.append(mask_bit | length)
    elif length < 65536:
        head.append(mask_bit | 126)
        head += length.to_bytes(2, "big")
    else:
        head.append(mask_bit | 127)
        head += length.to_bytes(8, "big")
    if mask:
        head += mask
        payload = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
    return bytes(head) + payload


async def _pipe(
    client_reader: asyncio.StreamReader,
    client_writer: asyncio.StreamWriter,
    up_reader: asyncio.StreamReader,
    up_writer: asyncio.StreamWriter,
    client_rest: bytes,
    up_rest: bytes,
) -> None:
    async def one_way(
        src: asyncio.StreamReader,
        dst: asyncio.StreamWriter,
        initial: bytes,
        rewrite: bool,
        gate: _IbTargetGate | None,
    ) -> None:
        try:
            if initial:
                if rewrite:
                    initial = _rewrite_auto_attach(initial)
                if gate is not None:
                    initial = gate.feed(initial)
                if initial:
                    dst.write(initial)
                    await dst.drain()
            while True:
                chunk = await src.read(65536)
                if not chunk:
                    if rewrite:
                        dst.write(_ws_close(masked=True))
                        await dst.drain()
                    break
                if rewrite:
                    chunk = _rewrite_auto_attach(chunk)
                if gate is not None:
                    chunk = gate.feed(chunk)
                if not chunk:
                    continue
                dst.write(chunk)
                await dst.drain()
        except Exception:
            return

    forward = {
        asyncio.create_task(one_way(client_reader, up_writer, client_rest, True, None)),
        asyncio.create_task(one_way(up_reader, client_writer, up_rest, False, _IbTargetGate())),
    }
    try:
        done, pending = await asyncio.wait(forward, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
    finally:
        for stream in (client_writer, up_writer):
            try:
                stream.close()
            except Exception:
                pass
