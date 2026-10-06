"""Apply controller-published targets to this process's egress interfaces."""

from __future__ import annotations

from dataclasses import dataclass
from subprocess import PIPE, STDOUT
import time
from typing import Any

from channel_mininet.channel_schedule import Snapshot, netem_delay_us
from channel_mininet.runtime.names import interface_name
from channel_mininet.schema import Scene


@dataclass(frozen=True, slots=True)
class Egress:
    link_id: str
    direction: str
    node_id: str
    interface: str


class ChannelShaper:
    """Each direction is shaped once, at its sender's owned interface."""

    def __init__(self, scene: Scene, network: Any, worker_ids: tuple[str, ...]):
        self.scene = scene
        self.network = network
        self.worker_ids = frozenset(worker_ids)
        self.egresses = tuple(
            Egress(link.id, direction, sender, interface_name(scene.experiment, link.id, sender))
            for link in scene.links
            for direction, sender in (("a_to_b", link.a), ("b_to_a", link.b))
            if scene.nodes[sender].worker in self.worker_ids
        )
        self._configured: set[str] = set()
        self._gated = False

    def _run(self, egress: Egress, args: list[str]) -> None:
        node = self.network.get(egress.node_id)
        process = node.popen(args, stdout=PIPE, stderr=STDOUT)
        try:
            output, _ = process.communicate(timeout=15)
        except Exception:
            process.kill()
            process.communicate()
            raise
        if process.returncode:
            raise RuntimeError(
                f"{egress.link_id} {egress.direction} {egress.interface}: "
                f"{' '.join(args)} failed: {output.decode('utf-8', 'replace').strip()}"
            )

    def gate(self) -> bool:
        """Close every owned logical link; return whether a new gate was applied."""
        if self._gated:
            return False
        errors = []
        for egress in self.egresses:
            try:
                self._run(egress, ["ip", "link", "set", "dev", egress.interface, "down"])
            except Exception as exc:
                errors.append(str(exc))
        if errors:
            raise RuntimeError("cannot close all channel interfaces: " + "; ".join(errors))
        self._gated = True
        return True

    def ungate(self) -> dict[str, int]:
        if not self._gated:
            return {}
        times: dict[str, int] = {}
        for egress in self.egresses:
            self._run(egress, ["ip", "link", "set", "dev", egress.interface, "up"])
            worker = self.scene.nodes[egress.node_id].worker
            times[worker] = time.time_ns()
        self._gated = False
        return times

    def apply(self, snapshot: Snapshot) -> dict[str, int]:
        states = {link.link_id: link for link in snapshot.links}
        times = {worker: time.time_ns() for worker in self.worker_ids}
        for egress in self.egresses:
            link = states.get(egress.link_id)
            if link is None:
                if egress.interface in self._configured:
                    self._run(egress, ["tc", "qdisc", "del", "dev", egress.interface, "root"])
                    self._configured.remove(egress.interface)
                    worker = self.scene.nodes[egress.node_id].worker
                    times[worker] = time.time_ns()
                continue
            target = getattr(link, egress.direction)
            rate = round(target.bandwidth_mbps * 1_000_000)
            delay_us = netem_delay_us(target.netem_delay_ms)
            if rate < 1 or (target.netem_delay_ms > 0 and delay_us == 0):
                raise RuntimeError(f"{egress.link_id} {egress.direction} is below tc precision")
            dev = ["dev", egress.interface]
            configured = egress.interface in self._configured
            if not configured:
                self._run(egress, ["tc", "qdisc", "add", *dev, "root", "handle", "1:",
                                   "htb", "default", "1"])
            try:
                self._run(egress, ["tc", "class", "change" if configured else "add", *dev,
                                   "parent", "1:", "classid", "1:1", "htb",
                                   "rate", f"{rate}bit", "ceil", f"{rate}bit"])
                self._run(egress, ["tc", "qdisc", "change" if configured else "add", *dev,
                                   "parent", "1:1", "handle", "10:", "netem", "delay",
                                   f"{delay_us}us"])
            except Exception:
                if not configured:
                    self._run(egress, ["tc", "qdisc", "del", *dev, "root"])
                raise
            self._configured.add(egress.interface)
            worker = self.scene.nodes[egress.node_id].worker
            times[worker] = time.time_ns()
        return times
