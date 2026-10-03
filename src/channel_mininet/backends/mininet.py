"""Build Mininet Topo objects from the shared scene.

The basic mode uses ordinary Mininet hosts and OVS bridges. The optional
container adapter remains separate and needs Docker-backed node classes.
"""

from __future__ import annotations

from typing import Any, Mapping

from channel_mininet.runtime.names import interface_name
from channel_mininet.schema import Link, Scene, SceneError, Switch
from channel_mininet.topology.placement import plan_worker


def make_basic_topo(
    scene: Scene, worker_id: str | None = None, *, controlled: bool = False
) -> Any:
    """Build one worker, or the full scene, with ordinary Mininet nodes.

    Bridge mode learns MAC addresses without a controller. Controlled mode
    uses OpenFlow 1.3 and lets the controller select paths through cycles.
    """

    scene.validate()
    hosts, switches, links = _selection(scene, worker_id)
    if not controlled:
        _reject_switch_cycles(switches, links)
    switch_options = {"failMode": "secure", "protocols": "OpenFlow13"} if controlled else None
    return _build_topo(scene, hosts, switches, links, switch_options=switch_options)


def make_worker_topo(
    scene: Scene, worker_id: str, *, docker_host_class: type, docker_switch_class: type
) -> Any:
    """Return a Mininet Topo for local nodes and local links only.

    Cross-worker links have one coordinator owner and are intentionally not
    added to either worker's Topo. Both workers call this same function.
    """

    scene.validate()
    hosts, switches, links = _selection(scene, worker_id)
    return _build_topo(
        scene,
        hosts,
        switches,
        links,
        host_class=docker_host_class,
        switch_class=docker_switch_class,
    )


def _selection(scene: Scene, worker_id: str | None):
    if worker_id is None:
        return scene.hosts, scene.switches, scene.links
    plan = plan_worker(scene, worker_id)
    return plan.hosts, plan.switches, plan.local_links


def _build_topo(
    scene: Scene,
    hosts,
    switches,
    links,
    *,
    host_class: type | None = None,
    switch_class: type | None = None,
    switch_options: Mapping[str, Any] | None = None,
) -> Any:
    try:
        from mininet.topo import Topo
    except ImportError as exc:
        raise RuntimeError("Mininet is not importable by this Python interpreter") from exc

    topo = Topo()
    for switch in sorted(switches, key=lambda item: item.id):
        options: dict[str, Any] = {"dpid": switch.dpid}
        if switch_options:
            options.update(switch_options)
        if switch_class is not None:
            options["cls"] = switch_class
        topo.addSwitch(switch.id, **options)
    for host in sorted(hosts, key=lambda item: item.id):
        options = {
            "ip": f"{host.ip}/{scene.subnet.prefixlen}",
            "mac": host.mac,
        }
        if host_class is not None:
            options["cls"] = host_class
        topo.addHost(host.id, **options)
    for link in sorted(links, key=lambda item: item.id):
        topo.addLink(
            link.a,
            link.b,
            intfName1=interface_name(scene.experiment, link.id, link.a),
            intfName2=interface_name(scene.experiment, link.id, link.b),
        )
    return topo


def _reject_switch_cycles(
    switches: tuple[Switch, ...], links: tuple[Link, ...]
) -> None:
    parent = {switch.id: switch.id for switch in switches}

    def find(node_id: str) -> str:
        while parent[node_id] != node_id:
            parent[node_id] = parent[parent[node_id]]
            node_id = parent[node_id]
        return node_id

    for link in links:
        if link.a not in parent or link.b not in parent:
            continue
        a, b = find(link.a), find(link.b)
        if a == b:
            raise SceneError(
                f"basic OVS bridge mode cannot start cyclic switch fabric at {link.id!r}"
            )
        parent[a] = b
