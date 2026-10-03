"""Foreground lifecycle for the basic, single-machine Mininet network."""

from __future__ import annotations

import os
from ipaddress import IPv4Address, ip_address
import subprocess

from channel_mininet.backends.mininet import make_basic_topo
from channel_mininet.schema import Scene
from channel_mininet.topology.placement import plan_worker


def run_basic_network(
    scene: Scene,
    worker_id: str | None = None,
    *,
    controller_host: str | None = None,
    controller_port: int = 6653,
) -> None:
    """Start a foreground Mininet network, optionally using a remote controller.

    With ``worker_id=None`` this starts both configured partitions in one
    Mininet process, including their connecting link. A worker ID starts only
    its own local topology. No global Mininet cleanup command is invoked.
    """

    if not hasattr(os, "geteuid"):
        raise RuntimeError("Mininet network startup requires Linux")
    if os.geteuid() != 0:
        raise RuntimeError("Mininet network startup requires root; use sudo")
    if controller_host is not None:
        if worker_id is not None and plan_worker(scene, worker_id).boundary_links:
            raise RuntimeError(
                "controlled single-worker mode needs cross-worker links, which are not implemented"
            )
        try:
            if not isinstance(ip_address(controller_host), IPv4Address):
                raise ValueError("IPv6 is not supported by this startup mode")
        except ValueError as exc:
            raise RuntimeError("controller host must be an IPv4 address") from exc
        if not 1 <= controller_port <= 65535:
            raise RuntimeError("controller port must be between 1 and 65535")
    _check_bridge_names(scene, worker_id)
    try:
        from mininet.cli import CLI
        from mininet.log import setLogLevel
        from mininet.net import Mininet
        from mininet.node import Host, OVSBridge, OVSSwitch, RemoteController
    except ImportError as exc:
        raise RuntimeError("Mininet is not importable by this Python interpreter") from exc

    topo = make_basic_topo(scene, worker_id, controlled=controller_host is not None)
    setLogLevel("info")
    network = Mininet(
        topo=topo,
        host=Host,
        switch=OVSSwitch if controller_host is not None else OVSBridge,
        controller=None,
        build=False,
        cleanup=False,
        autoSetMacs=False,
        autoStaticArp=False,
    )
    try:
        if controller_host is not None:
            network.addController(
                "mdc0", controller=RemoteController, ip=controller_host, port=controller_port
            )
        network.build()
        network.start()
        if controller_host is not None:
            print(f"Network started with remote controller {controller_host}:{controller_port}.")
            print("Wait for the controller's flow confirmation before testing traffic.")
        else:
            print("Network started in OVS bridge mode.")
        print("Use Mininet CLI commands; type 'exit' to stop it.")
        CLI(network)
    finally:
        network.stop()


def _check_bridge_names(scene: Scene, worker_id: str | None) -> None:
    """Mininet may replace a same-named OVS bridge, so reject conflicts first."""

    wanted = {
        switch.id
        for switch in scene.switches
        if worker_id is None or switch.worker == worker_id
    }
    try:
        result = subprocess.run(
            ["ovs-vsctl", "--timeout=5", "list-br"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("ovs-vsctl is missing; install Open vSwitch") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("timed out while reading OVS bridges") from exc
    if result.returncode != 0:
        raise RuntimeError(f"cannot read OVS bridges: {result.stderr.strip()}")
    conflicts = wanted.intersection(result.stdout.splitlines())
    if conflicts:
        raise RuntimeError(f"OVS bridge names already exist: {', '.join(sorted(conflicts))}")
