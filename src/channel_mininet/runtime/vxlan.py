"""One OVS VXLAN port per cross-worker link endpoint."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import blake2s
from ipaddress import IPv4Address
import json
import subprocess
import sys

from channel_mininet.runtime.deployment import Deployment
from channel_mininet.runtime.names import interface_name
from channel_mininet.schema import Scene, SceneError
from channel_mininet.topology.placement import plan_worker


@dataclass(frozen=True, slots=True)
class Tunnel:
    link_id: str
    switch_id: str
    port_name: str
    local_ip: IPv4Address
    remote_ip: IPv4Address
    vni: int


def _private_name(tunnel: Tunnel, prefix: str) -> str:
    identity = f"{tunnel.link_id}\0{tunnel.switch_id}\0{prefix}".encode("utf-8")
    return prefix + blake2s(identity, digest_size=7).hexdigest()


def plan_tunnels(scene: Scene, deployment: Deployment, worker_id: str) -> tuple[Tunnel, ...]:
    """Assign a stable VNI and the same port name expected by the controller."""

    plan = plan_worker(scene, worker_id)
    nodes = scene.nodes
    used_vnis: dict[int, str] = {}
    tunnels = []
    for link in sorted(scene.links, key=lambda item: item.id):
        if nodes[link.a].worker == nodes[link.b].worker:
            continue
        identity = f"{scene.experiment}\0{link.id}".encode("utf-8")
        vni = int.from_bytes(blake2s(identity, digest_size=4).digest(), "big") % 16777215 + 1
        if vni in used_vnis:
            raise SceneError(f"VXLAN VNI collision between {used_vnis[vni]!r} and {link.id!r}")
        used_vnis[vni] = link.id
        for local_id, remote_id in ((link.a, link.b), (link.b, link.a)):
            if nodes[local_id].worker != worker_id:
                continue
            tunnels.append(Tunnel(
                link_id=link.id,
                switch_id=local_id,
                port_name=interface_name(scene.experiment, link.id, local_id),
                local_ip=deployment.workers[worker_id],
                remote_ip=deployment.workers[nodes[remote_id].worker],
                vni=vni,
            ))
    if len(tunnels) != len(plan.boundary_links):
        raise SceneError("boundary tunnel plan does not cover every local boundary link")
    return tuple(tunnels)


def check_local_underlay(address: IPv4Address) -> None:
    """Reject a worker ID pointed at a different physical machine."""

    try:
        result = subprocess.run(
            ["ip", "-j", "-4", "addr", "show"], capture_output=True, text=True,
            check=True, timeout=10,
        )
        interfaces = json.loads(result.stdout)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError) as exc:
        raise RuntimeError(f"cannot inspect local IPv4 addresses: {exc}") from exc
    assigned = {
        entry.get("local") for interface in interfaces
        for entry in interface.get("addr_info", [])
    }
    if str(address) not in assigned:
        raise RuntimeError(f"worker underlay address {address} is not assigned to this machine")


def add_tunnel(tunnel: Tunnel, owner: str) -> None:
    """Create an OVS port atomically; an existing port is a conflict."""

    command = [
        "ovs-vsctl", "--timeout=10", "--", "add-port", tunnel.switch_id, tunnel.port_name,
        "--", "set", "Interface", tunnel.port_name, "type=vxlan",
        f"options:local_ip={tunnel.local_ip}",
        f"options:remote_ip={tunnel.remote_ip}",
        f"options:key={tunnel.vni}",
        "options:dst_port=4789",
        f"external_ids:mdnet_owner={owner}",
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"cannot create VXLAN port {tunnel.port_name}: {exc}") from exc
    if result.returncode != 0:
        raise RuntimeError(f"cannot create VXLAN port {tunnel.port_name}: {result.stderr.strip()}")


def _run(command: list[str]) -> str:
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"cannot run {' '.join(command)}: {exc}") from exc
    if result.returncode:
        raise RuntimeError(f"{' '.join(command)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def add_shaped_tunnel(tunnel: Tunnel, owner: str) -> None:
    """Put a dedicated veth egress between the logical switch and VXLAN.

    The switch-side veth keeps the controller's existing expected port name.
    Its egress qdisc shapes only traffic sent toward this one tunnel.
    """
    bridge = _private_name(tunnel, "b")
    peer = _private_name(tunnel, "p")
    vxlan = _private_name(tunnel, "v")
    created_veth = False
    created_bridge = False
    try:
        _run(["ip", "link", "add", tunnel.port_name, "type", "veth", "peer", "name", peer])
        created_veth = True
        _run(["ovs-vsctl", "--timeout=10", "add-br", bridge])
        created_bridge = True
        _run(["ovs-vsctl", "--timeout=10", "set", "Bridge", bridge,
              f"external_ids:mdnet_owner={owner}"])
        _run(["ovs-vsctl", "--timeout=10", "add-port", tunnel.switch_id, tunnel.port_name,
              "--", "set", "Interface", tunnel.port_name,
              f"external_ids:mdnet_owner={owner}"])
        _run(["ovs-vsctl", "--timeout=10", "add-port", bridge, peer])
        _run(["ovs-vsctl", "--timeout=10", "add-port", bridge, vxlan,
              "--", "set", "Interface", vxlan, "type=vxlan",
              f"options:local_ip={tunnel.local_ip}",
              f"options:remote_ip={tunnel.remote_ip}",
              f"options:key={tunnel.vni}", "options:dst_port=4789"])
        _run(["ip", "link", "set", "dev", tunnel.port_name, "up"])
        _run(["ip", "link", "set", "dev", peer, "up"])
    except Exception:
        if created_bridge:
            subprocess.run(["ovs-vsctl", "--timeout=10", "--if-exists", "del-br", bridge],
                           capture_output=True, check=False)
        if created_veth:
            subprocess.run(["ip", "link", "del", tunnel.port_name],
                           capture_output=True, check=False)
        raise


def remove_shaped_tunnels(tunnels: list[Tunnel], owner: str) -> None:
    """Remove only bridges tagged with this process's owner token."""
    for tunnel in reversed(tunnels):
        bridge = _private_name(tunnel, "b")
        try:
            current = _run(["ovs-vsctl", "--timeout=10", "--if-exists", "get",
                            "Bridge", bridge, "external_ids:mdnet_owner"])
            if current.strip('"') != owner:
                continue
            _run(["ovs-vsctl", "--timeout=10", "--if-exists", "del-br", bridge])
            _run(["ovs-vsctl", "--timeout=10", "--if-exists", "del-port",
                  tunnel.switch_id, tunnel.port_name])
            _run(["ip", "link", "del", tunnel.port_name])
        except RuntimeError as exc:
            print(f"Could not remove shaped tunnel {tunnel.port_name}: {exc}", file=sys.stderr)


def remove_tunnels(tunnels: list[Tunnel], owner: str) -> None:
    """Only remove ports created by this process, in reverse order."""

    for tunnel in reversed(tunnels):
        try:
            current = subprocess.run(
                ["ovs-vsctl", "--timeout=10", "--if-exists", "get", "Interface",
                 tunnel.port_name, "external_ids:mdnet_owner"],
                capture_output=True, text=True, check=False, timeout=15,
            )
            if current.returncode != 0:
                print(f"Could not inspect VXLAN port {tunnel.port_name}: {current.stderr.strip()}",
                      file=sys.stderr)
                continue
            if current.stdout.strip().strip('"') != owner:
                continue
            result = subprocess.run(
                ["ovs-vsctl", "--timeout=10", "--if-exists", "del-port",
                 tunnel.switch_id, tunnel.port_name],
                capture_output=True, text=True, check=False, timeout=15,
            )
            if result.returncode != 0:
                print(f"Could not remove VXLAN port {tunnel.port_name}: {result.stderr.strip()}",
                      file=sys.stderr)
        except (OSError, subprocess.TimeoutExpired) as exc:
            print(f"Could not remove VXLAN port {tunnel.port_name}: {exc}", file=sys.stderr)
