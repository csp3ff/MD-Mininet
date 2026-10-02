"""Foreground lifecycle for the basic, single-machine Mininet network."""

from __future__ import annotations

import os
import subprocess

from channel_mininet.backends.mininet import make_basic_topo
from channel_mininet.schema import Scene


def run_basic_network(scene: Scene, worker_id: str | None = None) -> None:
    """Start ordinary Mininet hosts and OVS bridges until the CLI exits.

    With ``worker_id=None`` this starts both configured partitions in one
    Mininet process, including their connecting link. A worker ID starts only
    its own local topology. No global Mininet cleanup command is invoked.
    """

    if not hasattr(os, "geteuid"):
        raise RuntimeError("Mininet network startup requires Linux")
    if os.geteuid() != 0:
        raise RuntimeError("Mininet network startup requires root; use sudo")
    _check_bridge_names(scene, worker_id)
    try:
        from mininet.cli import CLI
        from mininet.log import setLogLevel
        from mininet.net import Mininet
        from mininet.node import Host, OVSBridge
    except ImportError as exc:
        raise RuntimeError("Mininet is not importable by this Python interpreter") from exc

    topo = make_basic_topo(scene, worker_id)
    setLogLevel("info")
    network = Mininet(
        topo=topo,
        host=Host,
        switch=OVSBridge,
        controller=None,
        build=False,
        cleanup=False,
        autoSetMacs=False,
        autoStaticArp=False,
    )
    try:
        network.build()
        network.start()
        print("Network started. Use Mininet CLI commands; type 'exit' to stop it.")
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
