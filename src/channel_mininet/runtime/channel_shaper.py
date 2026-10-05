"""Apply controller-published targets to this process's egress interfaces."""

from __future__ import annotations

from dataclasses import dataclass
from subprocess import PIPE, STDOUT
import time
from typing import Any

from channel_mininet.channel_schedule import Snapshot
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

    def gate(self) -> None:
        """Close every owned logical link after loss of channel control."""
        errors = []
        for egress in self.egresses:
            try:
                self._run(egress, ["ip", "link", "set", "dev", egress.interface, "down"])
            except Exception as exc:
                errors.append(str(exc))
        self._gated = True
        if errors:
            raise RuntimeError("cannot close all channel interfaces: " + "; ".join(errors))

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
        times: dict[str, int] = {}
        for egress in self.egresses:
            link = states[egress.link_id]
            target = getattr(link, egress.direction)
            rate = round(target.bandwidth_mbps * 1_000_000)
            if rate < 1 or (0 < target.netem_delay_ms < 0.001):
                raise RuntimeError(f"{egress.link_id} {egress.direction} is below tc precision")
            dev = ["dev", egress.interface]
            configured = egress.interface in self._configured
            if not configured:
                self._run(egress, ["tc", "qdisc", "add", *dev, "root", "handle", "1:",
                                   "htb", "default", "1"])
            self._run(egress, ["tc", "class", "change" if configured else "add", *dev,
                               "parent", "1:", "classid", "1:1", "htb",
                               "rate", f"{rate}bit", "ceil", f"{rate}bit"])
            self._run(egress, ["tc", "qdisc", "change" if configured else "add", *dev,
                               "parent", "1:1", "handle", "10:", "netem", "delay",
                               f"{target.netem_delay_ms:.9f}ms"])
            self._configured.add(egress.interface)
            worker = self.scene.nodes[egress.node_id].worker
            times[worker] = time.time_ns()
        return times
