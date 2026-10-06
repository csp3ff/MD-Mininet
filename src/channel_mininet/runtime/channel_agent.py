"""Worker-side channel executor; it never reads the schedule file."""

from __future__ import annotations

import socket
from threading import Event, Lock, Thread
import time

from channel_mininet.channel_schedule import Snapshot, parse_snapshot
from channel_mininet.runtime.channel_shaper import ChannelShaper
from channel_mininet.runtime.channel_wire import JsonConnection
from channel_mininet.schema import Scene, scene_fingerprint


HEARTBEAT_TIMEOUT_S = 4.0


class ChannelAgent:
    def __init__(self, scene: Scene, shaper: ChannelShaper, worker_ids: tuple[str, ...],
                 host: str, port: int):
        self.scene = scene
        self.shaper = shaper
        self.worker_ids = worker_ids
        self.host = host
        self.port = port
        self._stop = Event()
        self._lock = Lock()
        self._shaper_lock = Lock()
        self._wire: JsonConnection | None = None
        self._apply_thread: Thread | None = None
        self._thread = Thread(target=self._run, name="md-channel-agent", daemon=True)
        self._started = False
        self._run_id: str | None = None
        self._schedule_digest: str | None = None
        self._pending: Snapshot | None = None
        self._pending_at_ns: int | None = None
        self._committed_index: int | None = None
        self._current_index: int | None = None
        self._last_gate_reason: str | None = None

    def start(self) -> None:
        self.shaper.gate()
        self._thread.start()
        self._started = True

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            wire = self._wire
            self._wire = None
        if wire is not None:
            try:
                wire.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            wire.connection.close()
        if self._started:
            self._thread.join(timeout=2)
        if self._apply_thread is not None:
            self._apply_thread.join(timeout=20)

    def _gate(self, reason: str) -> None:
        detected_at_ns = time.time_ns()
        try:
            with self._shaper_lock:
                changed = self.shaper.gate()
                if not changed and reason == self._last_gate_reason:
                    return
                self._last_gate_reason = reason
            gated_at_ns = time.time_ns()
            if changed:
                print(f"Channel forwarding stopped: {reason}; detected_at_unix_ns="
                      f"{detected_at_ns}; gated_at_unix_ns={gated_at_ns}; "
                      f"shutdown_window_ms={(gated_at_ns - detected_at_ns) / 1e6:.3f}")
            else:
                print(f"Channel forwarding remains stopped: {reason}; "
                      f"detected_at_unix_ns={detected_at_ns}")
        except RuntimeError as exc:
            print(f"Channel gate failed: {exc}; detected_at_unix_ns={detected_at_ns}; "
                  f"failure_at_unix_ns={time.time_ns()}")

    def _run(self) -> None:
        while not self._stop.is_set():
            wire: JsonConnection | None = None
            try:
                connection = socket.create_connection((self.host, self.port), timeout=5)
                wire = JsonConnection(connection)
                with self._lock:
                    self._wire = wire
                    self._run_id = None
                    self._schedule_digest = None
                self._serve(wire)
            except Exception as exc:
                if not self._stop.is_set():
                    with self._lock:
                        self._wire = None
                    self._gate(str(exc))
            finally:
                with self._lock:
                    self._wire = None
                    self._pending = None
                    self._pending_at_ns = None
                    self._committed_index = None
                if wire is not None:
                    wire.connection.close()
            self._stop.wait(2)

    def _serve(self, wire: JsonConnection) -> None:
        wire.send({"type": "hello", "protocol": 1,
                   "scene_digest": scene_fingerprint(self.scene),
                   "worker_ids": list(self.worker_ids)})
        last_rx = time.monotonic()
        while not self._stop.is_set():
            message = wire.receive()
            if message is None:
                if time.monotonic() - last_rx > HEARTBEAT_TIMEOUT_S:
                    raise TimeoutError("central controller channel heartbeat timed out")
                if self._run_id is not None:
                    wire.send({"type": "heartbeat", "run_id": self._run_id})
                continue
            last_rx = time.monotonic()
            kind = message.get("type")
            if kind == "welcome":
                if self._run_id is not None:
                    raise ValueError("duplicate channel welcome")
                if message.get("scene_digest") != scene_fingerprint(self.scene):
                    raise ValueError("controller scene_digest mismatch")
                run_id = message.get("run_id")
                digest = message.get("schedule_digest")
                if not isinstance(run_id, str) or not isinstance(digest, str):
                    raise ValueError("invalid controller channel welcome")
                self._run_id = run_id
                self._schedule_digest = digest
                self._current_index = None
            elif kind == "heartbeat_ack":
                if message.get("run_id") != self._run_id:
                    raise ValueError("controller run_id changed")
            elif kind == "prepare":
                self._prepare(wire, message)
            elif kind == "commit":
                self._commit(wire, message)
            elif kind == "abort":
                if message.get("run_id") != self._run_id:
                    raise ValueError("abort run_id mismatch")
                with self._lock:
                    self._pending = None
                    self._pending_at_ns = None
                    self._committed_index = None
                raise RuntimeError(str(message.get("reason", "controller aborted channel run")))
            else:
                raise ValueError(f"unexpected channel control message {kind!r}")

    def _prepare(self, wire: JsonConnection, message: dict) -> None:
        if message.get("run_id") != self._run_id or self._run_id is None:
            raise ValueError("prepare run_id mismatch")
        if (message.get("scene_digest") != scene_fingerprint(self.scene) or
                message.get("schedule_digest") != self._schedule_digest):
            raise ValueError("prepare scene or schedule digest mismatch")
        raw = message.get("snapshot")
        if not isinstance(raw, dict) or type(raw.get("index")) is not int:
            raise ValueError("prepare needs an indexed snapshot")
        snapshot = parse_snapshot(raw, self.scene, raw["index"])
        if self._current_index is not None and snapshot.index < self._current_index:
            raise ValueError("controller sent stale snapshot")
        activate_at = message.get("activate_at_unix_ns")
        if type(activate_at) is not int or activate_at <= time.time_ns():
            raise ValueError("prepare needs a future activation time")
        with self._lock:
            if self._pending is not None:
                raise ValueError("another channel snapshot is pending")
            self._pending = snapshot
            self._pending_at_ns = activate_at
            self._committed_index = None
        Thread(target=self._deadline_gate, args=(snapshot.index, activate_at), daemon=True).start()
        wire.send({"type": "ready", "run_id": self._run_id,
                   "index": snapshot.index, "digest": snapshot.digest})

    def _deadline_gate(self, index: int, activate_at_ns: int) -> None:
        remaining = max(0, (activate_at_ns - time.time_ns()) / 1e9)
        if self._stop.wait(remaining):
            return
        with self._lock:
            should_gate = (self._pending is not None and self._pending.index == index and
                           self._pending_at_ns == activate_at_ns and
                           self._committed_index != index)
        if should_gate:
            self._gate(f"snapshot {index} was not committed by its activation deadline")

    def _commit(self, wire: JsonConnection, message: dict) -> None:
        if message.get("run_id") != self._run_id:
            raise ValueError("commit run_id mismatch")
        with self._lock:
            snapshot = self._pending
            activate_at = self._pending_at_ns
            if (snapshot is None or message.get("index") != snapshot.index or
                    message.get("activate_at_unix_ns") != activate_at or
                    self._committed_index is not None):
                raise ValueError("commit does not match prepared snapshot")
            self._committed_index = snapshot.index
        if activate_at <= time.time_ns():
            raise TimeoutError("channel commit arrived after activation time")
        self._apply_thread = Thread(target=self._apply_at, args=(wire, snapshot, activate_at),
                                    daemon=True)
        self._apply_thread.start()

    def _apply_at(self, wire: JsonConnection, snapshot: Snapshot, activate_at_ns: int) -> None:
        if self._stop.wait(max(0, (activate_at_ns - time.time_ns()) / 1e9)):
            return
        with self._lock:
            if self._wire is not wire or self._committed_index != snapshot.index:
                return
        try:
            with self._shaper_lock:
                with self._lock:
                    if self._wire is not wire or self._committed_index != snapshot.index:
                        return
                applied_times = self.shaper.apply(snapshot)
                with self._lock:
                    if self._wire is not wire or self._stop.is_set():
                        raise RuntimeError("channel connection was lost during apply")
                applied_times.update(self.shaper.ungate())
                self._last_gate_reason = None
            applied_at = max(applied_times.values())
            with self._lock:
                self._current_index = snapshot.index
                self._pending = None
                self._pending_at_ns = None
                self._committed_index = None
            wire.send({"type": "applied", "run_id": self._run_id, "index": snapshot.index,
                       "ok": True, "applied_at_unix_ns": applied_at,
                       "applied_at_by_worker_ns": applied_times})
            print(f"Channel snapshot {snapshot.index} APPLIED for workers "
                  f"{', '.join(self.worker_ids)} at_unix_ns={applied_at}")
        except Exception as exc:
            self._gate(f"snapshot {snapshot.index} apply failed: {exc}")
            try:
                wire.send({"type": "applied", "run_id": self._run_id,
                           "index": snapshot.index, "ok": False, "error": str(exc)})
            except OSError:
                pass
