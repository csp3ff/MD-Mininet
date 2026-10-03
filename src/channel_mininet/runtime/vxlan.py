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
