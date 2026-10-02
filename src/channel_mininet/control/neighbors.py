"""Static IPv4 neighbor entries for the first version's single subnet."""

from __future__ import annotations

from dataclasses import dataclass
from ipaddress import IPv4Address

from channel_mininet.schema import Scene


@dataclass(frozen=True, slots=True)
class NeighborEntry:
    source_host: str
    target_host: str
    target_ip: IPv4Address
    target_mac: str


def build_static_neighbors(scene: Scene) -> tuple[NeighborEntry, ...]:
    """Return all directed host pairs without issuing any host commands."""

    entries = []
    for source in sorted(scene.hosts, key=lambda host: host.id):
        for target in sorted(scene.hosts, key=lambda host: host.id):
            if source.id != target.id:
                entries.append(NeighborEntry(source.id, target.id, target.ip, target.mac))
    return tuple(entries)
