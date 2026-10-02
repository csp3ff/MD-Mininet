"""Shortest-path forwarding for one IPv4 subnet across worker partitions."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from ipaddress import IPv4Address

from channel_mininet.schema import Scene, SceneError
from channel_mininet.topology.builder import StaticTopology, build_topology


@dataclass(frozen=True, slots=True)
class Route:
    switch_id: str
    destination_host: str
    destination_ip: IPv4Address
    output_link: str
    next_node: str
    hops_to_host: int


def build_routes(scene: Scene, topology: StaticTopology | None = None) -> tuple[Route, ...]:
    """Build one reverse shortest-path tree for each destination host.

    Equal-hop choices use sorted switch IDs, giving identical plans on every
    worker. Routes describe logical links; OpenFlow ports are resolved only
    after real OVS interfaces have been observed.
    """

    topology = topology or build_topology(scene)
    routes: list[Route] = []
    for host in sorted(scene.hosts, key=lambda item: item.id):
        attachment = topology.host_attachment[host.id]
        destination_switch = attachment.peer
        next_hop: dict[str, tuple[str, str, int]] = {
            destination_switch: (host.id, attachment.link_id, 1)
        }
        distance = {destination_switch: 0}
        queue = deque([destination_switch])
        while queue:
            current = queue.popleft()
            for edge in topology.switch_neighbors[current]:
                if edge.peer in distance:
                    continue
                distance[edge.peer] = distance[current] + 1
                next_hop[edge.peer] = (current, edge.link_id, distance[edge.peer] + 1)
                queue.append(edge.peer)
        if len(next_hop) != len(scene.switches):
            raise SceneError(f"no route from every switch to host {host.id!r}")
        for switch in sorted(scene.switches, key=lambda item: item.id):
            peer, link_id, hops = next_hop[switch.id]
            routes.append(Route(switch.id, host.id, host.ip, link_id, peer, hops))
    return tuple(routes)
