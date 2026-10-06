"""Remove resources left by a stopped Mininet worker for one scene scope."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys

from channel_mininet.runtime.deployment import load_deployment
from channel_mininet.runtime.names import planned_interface_names
from channel_mininet.runtime.vxlan import (
    check_local_underlay, plan_tunnels, shaped_bridge_name,
)
from channel_mininet.schema import SceneError, load_scene
from channel_mininet.topology.placement import plan_worker


def _run(command: list[str]) -> str:
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, check=False, timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"cannot run {' '.join(command)}: {exc}") from exc
    if result.returncode:
        raise RuntimeError(f"{' '.join(command)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _active_mininet_pids() -> list[int]:
    """Do not remove a live worker's bridges or its namespace interfaces."""
    active = []
    for entry in os.scandir("/proc"):
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            args = Path(entry.path, "cmdline").read_bytes().split(b"\0")
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise RuntimeError(f"cannot inspect process {entry.name}: {exc}") from exc
        if any(arg.startswith(b"mininet:") for arg in args):
            active.append(int(entry.name))
        elif any(
            (arg.rsplit(b"/", 1)[-1] == b"md-mininet" or
             arg == b"channel_mininet.cli") and
            i + 1 < len(args) and args[i + 1] == b"up"
            for i, arg in enumerate(args)
        ):
            active.append(int(entry.name))
    return sorted(active)


def _bridge_dpid(bridge: str) -> str | None:
    for column in ("other_config:datapath-id", "datapath_id"):
        value = _run(["ovs-vsctl", "--timeout=10", "get", "Bridge", bridge, column])
        if value not in ("", "[]"):
            return value.strip('"').lower()
    return None


def clean(scene_path: str, worker_id: str | None, deployment_path: str | None) -> None:
    if os.geteuid() != 0:
        raise RuntimeError("cleanup requires root; use sudo ./clean.sh")
    scene = load_scene(scene_path)
    if deployment_path is not None and worker_id is None:
        raise SceneError("--deployment requires --worker")

    if worker_id is None:
        node_ids = set(scene.nodes)
        switches = scene.switches
    else:
        plan = plan_worker(scene, worker_id)
        node_ids = set(plan.node_ids)
        switches = plan.switches

    private_bridges: set[str] = set()
    if deployment_path is not None:
        deployment = load_deployment(deployment_path, scene)
        check_local_underlay(deployment.workers[worker_id])
        private_bridges = {
            shaped_bridge_name(tunnel)
            for tunnel in plan_tunnels(scene, deployment, worker_id)
        }

    active = _active_mininet_pids()
    if active:
        raise RuntimeError(
            "Mininet processes are still running (PIDs: " +
            ", ".join(map(str, active)) + "); exit those CLIs first"
        )

    existing = set(_run(["ovs-vsctl", "--timeout=10", "list-br"]).splitlines())
    for switch in switches:
        if switch.id in existing and _bridge_dpid(switch.id) != switch.dpid:
            raise RuntimeError(
                f"bridge {switch.id} has a different or unreadable DPID; "
                "inspect it manually before cleanup"
            )
    for bridge in sorted(private_bridges & existing):
        owner = _run([
            "ovs-vsctl", "--timeout=10", "get", "Bridge", bridge,
            "external_ids:mdnet_owner",
        ])
        if owner in ("", "[]"):
            raise RuntimeError(
                f"private bridge {bridge} has no mdnet_owner tag; "
                "inspect its ports and remove it manually if it belongs to an old worker"
            )

    # Preflight every target before changing OVS or Linux interfaces.
    names = sorted({
        name for (_, node_id), name in planned_interface_names(scene).items()
        if node_id in node_ids
    })
    for bridge in sorted(private_bridges & existing):
        print(f"deleting private bridge {bridge}")
        _run(["ovs-vsctl", "--timeout=10", "--if-exists", "del-br", bridge])
    for switch in switches:
        if switch.id in existing:
            print(f"deleting scene bridge {switch.id}")
            _run(["ovs-vsctl", "--timeout=10", "--if-exists", "del-br", switch.id])
    for name in names:
        result = subprocess.run(
            ["ip", "link", "show", "dev", name],
            capture_output=True, text=True, check=False, timeout=15,
        )
        if result.returncode == 0:
            print(f"deleting interface {name}")
            _run(["ip", "link", "delete", "dev", name])
        elif "does not exist" not in result.stderr and "Cannot find device" not in result.stderr:
            raise RuntimeError(f"cannot inspect interface {name}: {result.stderr.strip()}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", default="configs/two_workers.json")
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--worker")
    scope.add_argument("--all-workers", action="store_true")
    parser.add_argument("--deployment")
    args = parser.parse_args(argv)
    try:
        clean(args.scene, args.worker, args.deployment)
    except (RuntimeError, SceneError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"md-clean: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
