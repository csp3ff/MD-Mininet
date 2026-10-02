"""Choose a local partition without changing the worker implementation."""

from __future__ import annotations

from dataclasses import dataclass

from channel_mininet.schema import Host, Link, Scene, SceneError, Switch, scene_fingerprint


@dataclass(frozen=True, slots=True)
class WorkerPlan:
    worker_id: str
    scene_digest: str
    hosts: tuple[Host, ...]
    switches: tuple[Switch, ...]
    local_links: tuple[Link, ...]
    boundary_links: tuple[Link, ...]

    @property
    def node_ids(self) -> frozenset[str]:
        return frozenset(node.id for node in (*self.hosts, *self.switches))


def plan_worker(scene: Scene, worker_id: str) -> WorkerPlan:
    """Return nodes owned by this worker and links requiring coordination.

    A boundary link is not created by either worker. A separate coordinator
    owns its lifecycle, avoiding duplicate veth creation and cross-worker
    deletion. All worker processes execute this exact same function.
    """

    if worker_id not in scene.workers:
        raise SceneError(f"worker {worker_id!r} is absent from scene")
    hosts = tuple(host for host in scene.hosts if host.worker == worker_id)
    switches = tuple(switch for switch in scene.switches if switch.worker == worker_id)
    node_ids = {node.id for node in (*hosts, *switches)}
    local_links = tuple(
        link for link in scene.links if link.a in node_ids and link.b in node_ids
    )
    boundary_links = tuple(
        link for link in scene.links if (link.a in node_ids) != (link.b in node_ids)
    )
    return WorkerPlan(worker_id, scene_fingerprint(scene), hosts, switches, local_links, boundary_links)
