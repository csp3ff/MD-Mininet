"""Small, bounded JSON-lines channel control transport."""

from __future__ import annotations

import json
import socket
from threading import Lock
from typing import Any


MAX_MESSAGE_BYTES = 8 * 1024 * 1024


class JsonConnection:
    def __init__(self, connection: socket.socket):
        self.connection = connection
        self.connection.settimeout(1.0)
        self._buffer = bytearray()
        self._send_lock = Lock()

    def send(self, message: dict[str, Any]) -> None:
        data = json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n"
        if len(data) > MAX_MESSAGE_BYTES:
            raise ValueError("channel control message is too large")
        with self._send_lock:
            self.connection.sendall(data)

    def receive(self) -> dict[str, Any] | None:
        """Return None on socket timeout; raise EOFError on disconnect."""
        while True:
            newline = self._buffer.find(b"\n")
            if newline >= 0:
                if newline + 1 > MAX_MESSAGE_BYTES:
                    raise ValueError("channel control message is too large")
                line = bytes(self._buffer[:newline])
                del self._buffer[:newline + 1]
                try:
                    value = json.loads(line)
                except (ValueError, UnicodeDecodeError) as exc:
                    raise ValueError("invalid channel control JSON") from exc
                if not isinstance(value, dict):
                    raise ValueError("channel control message must be an object")
                return value
            if len(self._buffer) > MAX_MESSAGE_BYTES:
                raise ValueError("channel control message is too large")
            try:
                chunk = self.connection.recv(65536)
            except socket.timeout:
                return None
            if not chunk:
                raise EOFError("channel control connection closed")
            self._buffer.extend(chunk)
