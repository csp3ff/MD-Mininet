"""Controller-owned publication and barrier for channel snapshots.

This server runs inside ``md-controller``.  It is not a second time authority.
All workers receive the same complete snapshot; each applies its own egresses.
"""

from __future__ import annotations

import socket
from threading import Condition, Thread
import time
from typing import Any, Callable
from uuid import uuid4

from channel_mininet.channel_schedule import ChannelSchedule, Snapshot
from channel_mininet.runtime.channel_wire import JsonConnection
from channel_mininet.schema import Scene


READY_TIMEOUT_S = 15.0
APPLIED_TIMEOUT_S = 15.0
COMMIT_LEAD_NS = 2_000_000_000
HEARTBEAT_TIMEOUT_S = 4.0


class _Client:
    def __init__(self, wire: JsonConnection, workers: frozenset[str]):
        self.wire = wire
        self.workers = workers
        self.last_seen = time.monotonic()
        self.expected_index: int | None = None
        self.committed_index: int | None = None
        self.ready_index: int | None = None
        self.applied: dict[int, dict[str, int]] = {}
        self.failed: str | None = None


class ChannelServer:
    def __init__(
        self, scene: Scene, schedule: ChannelSchedule, host: str, port: int,
        log: Any, on_worker_active: Callable[[frozenset[str], bool], None],
    ):
        self.scene = scene
        self.schedule = schedule
        self.log = log
        self.on_worker_active = on_worker_active
        self.run_id = uuid4().hex
        self._condition = Condition()
        self._clients: dict[str, _Client] = {}
        self._stopping = False
        self._failed = False
        self.current_index: int | None = None
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind((host, port))
        self._socket.listen()
        self._socket.settimeout(1.0)
        self._accept_thread = Thread(target=self._accept_loop, name="md-channel-accept", daemon=True)
        self._schedule_thread = Thread(target=self._schedule_loop, name="md-channel-timeline", daemon=True)

    def start(self) -> None:
        self._accept_thread.start()
        self._schedule_thread.start()
        self.log.info("Channel run %s listening; schedule digest %s", self.run_id, self.schedule.digest)

    def close(self) -> None:
        with self._condition:
            self._stopping = True
            clients = set(self._clients.values())
            self._condition.notify_all()
        self._socket.close()
        for client in clients:
            client.wire.connection.close()

    def _accept_loop(self) -> None:
        while not self._stopping:
            try:
                connection, _ = self._socket.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            Thread(target=self._client_loop, args=(connection,), daemon=True).start()

    def _client_loop(self, connection: socket.socket) -> None:
        wire = JsonConnection(connection)
        client: _Client | None = None
        registered = False
        try:
            deadline = time.monotonic() + READY_TIMEOUT_S
            hello = None
            while hello is None and time.monotonic() < deadline:
                hello = wire.receive()
            if hello is None or hello.get("type") != "hello":
                raise ValueError("expected channel hello")
            if (hello.get("scene_digest") != self.schedule.scene_digest or
                    type(hello.get("protocol")) is not int or hello["protocol"] != 1):
                raise ValueError("channel hello scene or protocol mismatch")
            raw_workers = hello.get("worker_ids")
            if not isinstance(raw_workers, list) or not raw_workers or not all(
                isinstance(item, str) for item in raw_workers
            ):
                raise ValueError("channel hello requires worker_ids")
            workers = frozenset(raw_workers)
            if len(workers) != len(raw_workers) or not workers <= set(self.scene.workers):
                raise ValueError("channel hello has duplicate or unknown worker")
            client = _Client(wire, workers)
            wire.send({"type": "welcome", "run_id": self.run_id,
                       "schedule_digest": self.schedule.digest,
                       "scene_digest": self.schedule.scene_digest})
            with self._condition:
                if any(worker in self._clients for worker in workers):
                    raise ValueError("channel worker already connected")
                for worker in workers:
                    self._clients[worker] = client
                registered = True
                self._condition.notify_all()
            self.log.info("Channel workers connected: %s", sorted(workers))
            if self.current_index is not None:
                Thread(target=self._rejoin, args=(client,), daemon=True).start()
            while not self._stopping:
                message = wire.receive()
                if message is None:
                    if time.monotonic() - client.last_seen > HEARTBEAT_TIMEOUT_S:
                        raise TimeoutError("channel worker heartbeat timed out")
                    continue
                if message.get("run_id") != self.run_id:
                    raise ValueError("channel run_id mismatch")
                kind = message.get("type")
                with self._condition:
                    client.last_seen = time.monotonic()
                    if (kind == "ready" and client.expected_index is not None and
                            type(message.get("index")) is int and
                            message["index"] == client.expected_index):
                        if message.get("digest") != self.schedule.snapshots[client.expected_index].digest:
                            raise ValueError("channel snapshot digest mismatch")
                        client.ready_index = client.expected_index
                    elif (kind == "applied" and client.committed_index is not None and
                          type(message.get("index")) is int and
                          message["index"] == client.committed_index):
                        if message.get("ok") is not True:
                            client.failed = str(message.get("error", "unknown apply failure"))
                            self.on_worker_active(client.workers, False)
                        elif type(message.get("applied_at_unix_ns")) is int:
                            times = message.get("applied_at_by_worker_ns")
                            if (not isinstance(times, dict) or set(times) != client.workers or
                                    any(type(value) is not int for value in times.values())):
                                raise ValueError("applied message needs every worker timestamp")
                            client.applied[client.committed_index] = times
                            self.on_worker_active(client.workers, True)
                        else:
                            raise ValueError("applied message needs applied_at_unix_ns")
                    elif kind == "heartbeat":
                        wire.send({"type": "heartbeat_ack", "run_id": self.run_id,
                                   "current_index": self.current_index})
                    else:
                        raise ValueError(f"unexpected channel message {kind!r}")
                    self._condition.notify_all()
        except Exception as exc:
            self.log.warning("Channel worker connection ended: %s", exc)
        finally:
            connection.close()
            if client is not None and registered:
                with self._condition:
                    for worker in client.workers:
                        if self._clients.get(worker) is client:
                            del self._clients[worker]
                    self._condition.notify_all()
                self.on_worker_active(client.workers, False)
                if not self._stopping:
                    self._abort(f"channel workers {sorted(client.workers)} disconnected")

    def _all_clients(self) -> set[_Client] | None:
        if set(self._clients) != set(self.scene.workers):
            return None
        return set(self._clients.values())

    def _wait(self, predicate: Callable[[set[_Client]], bool], deadline: float) -> set[_Client] | None:
        with self._condition:
            while not self._stopping and not self._failed:
                clients = self._all_clients()
                if clients is not None:
                    if any(client.failed for client in clients):
                        return None
                    if predicate(clients):
                        return clients
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(remaining)
        return None

    def _send(self, clients: set[_Client], message: dict[str, Any]) -> bool:
        try:
            for client in clients:
                client.wire.send(message)
        except (OSError, ValueError) as exc:
            self.log.error("Channel publish failed: %s", exc)
            return False
        return True

    def _transition(self, snapshot: Snapshot, activate_at_ns: int | None) -> int | None:
        clients = self._wait(lambda _: True, time.monotonic() + READY_TIMEOUT_S)
        if clients is None:
            return None
        with self._condition:
            for client in clients:
                client.expected_index = snapshot.index
                client.ready_index = None
                client.committed_index = None
                client.failed = None
        if activate_at_ns is None:
            activate_at_ns = time.time_ns() + int(READY_TIMEOUT_S * 1e9) + COMMIT_LEAD_NS
        if not self._send(clients, {"type": "prepare", "run_id": self.run_id,
                                    "snapshot": snapshot.to_dict(),
                                    "activate_at_unix_ns": activate_at_ns,
                                    "scene_digest": self.schedule.scene_digest,
                                    "schedule_digest": self.schedule.digest}):
            return None
        ready = self._wait(lambda cs: cs == clients and all(
            client.ready_index == snapshot.index for client in cs
        ), time.monotonic() + READY_TIMEOUT_S)
        if ready is None:
            return None
        if time.time_ns() + 500_000_000 >= activate_at_ns:
            self.log.error("Channel snapshot %s missed its commit lead time", snapshot.index)
            return None
        with self._condition:
            for client in clients:
                client.committed_index = snapshot.index
        if not self._send(clients, {"type": "commit", "run_id": self.run_id,
                                    "index": snapshot.index,
                                    "activate_at_unix_ns": activate_at_ns}):
            return None
        applied = self._wait(lambda cs: cs == clients and all(
            snapshot.index in client.applied for client in cs
        ), time.monotonic() + APPLIED_TIMEOUT_S + max(0, (activate_at_ns - time.time_ns()) / 1e9))
        if applied is None:
            return None
        times = {worker: when for client in applied
                 for worker, when in client.applied[snapshot.index].items()}
        timestamps = list(times.values())
        self.current_index = snapshot.index
        self.log.info("Channel snapshot %s applied; schedule_digest=%s; snapshot_digest=%s; "
                      "reported max switch skew %.3f ms (requires synchronized clocks); "
                      "times_by_worker=%s", snapshot.index, self.schedule.digest, snapshot.digest,
                      (max(timestamps) - min(timestamps)) / 1e6, times)
        return activate_at_ns

    def _schedule_loop(self) -> None:
        with self._condition:
            while not self._stopping and not self._failed and self._all_clients() is None:
                self._condition.wait()
            if self._stopping or self._failed:
                return
        first = self._transition(self.schedule.snapshots[0], None)
        if first is None:
            self._abort("initial channel snapshot did not reach every worker")
            return
        for snapshot in self.schedule.snapshots[1:]:
            planned = first + snapshot.sim_time_ms * 1_000_000
            if self._transition(snapshot, planned) is None:
                self._abort(f"channel snapshot {snapshot.index} was not applied by all workers")
                return

    def _abort(self, reason: str) -> None:
        with self._condition:
            if self._failed or self._stopping:
                return
            self._failed = True
            clients = set(self._clients.values())
            for client in clients:
                client.expected_index = None
                client.committed_index = None
            self._condition.notify_all()
        self.log.error("Channel run %s failed: %s", self.run_id, reason)
        for client in clients:
            self.on_worker_active(client.workers, False)
        self._send(clients, {"type": "abort", "run_id": self.run_id, "reason": reason})

    def _rejoin(self, client: _Client) -> None:
        index = self.current_index
        if index is None:
            return
        snapshot = self.schedule.snapshots[index]
        activate_at_ns = time.time_ns() + int(READY_TIMEOUT_S * 1e9) + COMMIT_LEAD_NS
        with self._condition:
            client.expected_index = index
            client.ready_index = None
        if not self._send({client}, {"type": "prepare", "run_id": self.run_id,
                                     "snapshot": snapshot.to_dict(),
                                     "activate_at_unix_ns": activate_at_ns,
                                     "scene_digest": self.schedule.scene_digest,
                                     "schedule_digest": self.schedule.digest}):
            client.wire.connection.close()
            return
        with self._condition:
            deadline = time.monotonic() + READY_TIMEOUT_S
            while (client.ready_index != index and
                   all(self._clients.get(worker) is client for worker in client.workers) and
                   time.monotonic() < deadline):
                self._condition.wait(deadline - time.monotonic())
            if client.ready_index != index:
                client.wire.connection.close()
                return
            client.committed_index = index
        if not self._send({client}, {"type": "commit", "run_id": self.run_id,
                                     "index": index, "activate_at_unix_ns": activate_at_ns}):
            client.wire.connection.close()
