"""Deterministic graph projection of a validated scene."""

from __future__ import annotations

from dataclasses import dataclass
from collections import deque

from channel_mininet.schema import Host, Scene, SceneError, Switch


@dataclass(frozen=True, slots=True)
class Edge:
    peer: str
    link_id: str


@dataclass(frozen=True, slots=True)
class StaticTopology:
    switch_neighbors: dict[str, tuple[Edge, ...]]
    host_attachment: dict[str, Edge]


def build_topology(scene: Scene) -> StaticTopology:
    """Build the single fabric shared by all worker partitions.

    Routing requires that every switch can reach every other switch. This is
    checked here, so a scene cannot silently produce partial flow tables.
    """

    scene.validate()
    nodes = scene.nodes
    neighbors: dict[str, list[Edge]] = {switch.id: [] for switch in scene.switches}
    attachments: dict[str, Edge] = {}
    for link in scene.links:
        a, b = nodes[link.a], nodes[link.b]
        if isinstance(a, Switch) and isinstance(b, Switch):
            neighbors[a.id].append(Edge(b.id, link.id))
            neighbors[b.id].append(Edge(a.id, link.id))
        elif isinstance(a, Host):
            attachments[a.id] = Edge(b.id, link.id)
        else:
            attachments[b.id] = Edge(a.id, link.id)

    start = min(neighbors)
    reached = {start}
    pending = deque([start])
    while pending:
        current = pending.popleft()
        for edge in neighbors[current]:
            if edge.peer not in reached:
                reached.add(edge.peer)
                pending.append(edge.peer)
    if reached != set(neighbors):
        missing = ", ".join(sorted(set(neighbors) - reached))
        raise SceneError(f"switch fabric is disconnected; unreachable: {missing}")
    return StaticTopology(
        switch_neighbors={
            switch_id: tuple(sorted(edges, key=lambda edge: (edge.peer, edge.link_id)))
            for switch_id, edges in neighbors.items()
        },
        host_attachment=attachments,
    )
