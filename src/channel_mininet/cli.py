"""Scene inspection and foreground basic Mininet startup commands."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from channel_mininet.control.neighbors import build_static_neighbors
from channel_mininet.control.routing import build_routes
from channel_mininet.channel import build_channel_states, load_channel_profile
from channel_mininet.channel_schedule import load_channel_schedule
from channel_mininet.runtime.names import interface_name, planned_interface_names
from channel_mininet.runtime.deployment import load_deployment
from channel_mininet.runtime.vxlan import plan_tunnels
from channel_mininet.runtime.worker import run_basic_network
from channel_mininet.schema import SceneError, load_scene, scene_fingerprint
from channel_mininet.topology.builder import build_topology
from channel_mininet.topology.placement import plan_worker


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="md-mininet")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="validate a scene without deployment")
    validate.add_argument("scene")
    plan = commands.add_parser("plan", help="print the static plan for one worker")
    plan.add_argument("scene")
    plan.add_argument("--worker", required=True)
    plan.add_argument("--deployment", help="include physical VXLAN endpoints")
    channel_plan = commands.add_parser(
        "channel-plan", help="compute sourced directional link states without deployment"
    )
    channel_plan.add_argument("scene")
    channel_plan.add_argument("profile", help="JSON channel profile bound to the scene digest")
    up = commands.add_parser("up", help="start the basic Mininet network in the foreground")
    up.add_argument("scene")
    scope = up.add_mutually_exclusive_group(required=True)
    scope.add_argument("--worker", help="start one worker, including VXLAN with --deployment")
    scope.add_argument(
        "--all-workers", action="store_true", help="start all partitions on this machine"
    )
    up.add_argument("--controller-host", help="IPv4 address of an independently running controller")
    up.add_argument("--controller-port", type=int)
    up.add_argument("--deployment", help="shared multi-machine deployment YAML or JSON")
    up.add_argument("--channel", action="store_true",
                    help="receive controller-published channel time slices")
    up.add_argument("--channel-control-port", type=int,
                    help="central controller channel port (default 6654)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        scene = load_scene(args.scene)
        if args.command == "up":
            if args.controller_host is None and args.controller_port is not None:
                raise SceneError("--controller-port requires --controller-host")
            deployment = None
            if args.deployment:
                if args.all_workers:
                    raise SceneError("--deployment requires --worker")
                if args.controller_host is not None or args.controller_port is not None:
                    raise SceneError("--deployment supplies the controller address; omit --controller-host/port")
                deployment = load_deployment(args.deployment, scene)
            if args.channel_control_port is not None and not args.channel:
                raise SceneError("--channel-control-port requires --channel")
            if args.channel_control_port is not None and not 1 <= args.channel_control_port <= 65535:
                raise SceneError("--channel-control-port must be between 1 and 65535")
            if args.channel and deployment is None and args.controller_host is None:
                raise SceneError("--channel requires a central controller")
            if args.channel and deployment is not None and args.channel_control_port is not None:
                raise SceneError("--deployment supplies the channel control port")
            channel_port = (
                deployment.channel_port if deployment else
                6654 if args.channel_control_port is None else args.channel_control_port
            ) if args.channel else None
            openflow_port = (deployment.controller_port if deployment else
                             6653 if args.controller_port is None else args.controller_port)
            if channel_port is not None and channel_port == openflow_port:
                raise SceneError("channel control port must differ from OpenFlow port")
            run_basic_network(
                scene,
                None if args.all_workers else args.worker,
                controller_host=(str(deployment.controller_host) if deployment else args.controller_host),
                controller_port=openflow_port,
                channel_port=channel_port,
                deployment=deployment,
            )
            return 0
        if args.command == "channel-plan":
            try:
                version = json.loads(Path(args.profile).read_text(encoding="utf-8")).get("version")
            except (OSError, ValueError, AttributeError) as exc:
                raise SceneError(f"cannot inspect channel profile {args.profile}: {exc}") from exc
            if version == 2:
                schedule = load_channel_schedule(args.profile, scene, complete=False)
                result = {
                    "scene_digest": schedule.scene_digest,
                    "channel_schedule_digest": schedule.digest,
                    "revision": schedule.revision,
                    "snapshots": [],
                }
                for snapshot in schedule.snapshots:
                    covered = {link.link_id for link in snapshot.links}
                    entries = []
                    for target in snapshot.links:
                        link = scene.links_by_id[target.link_id]
                        for direction, sender in (("a_to_b", link.a), ("b_to_a", link.b)):
                            values = getattr(target, direction)
                            entries.append({
                                "link_id": target.link_id, "direction": direction,
                                "worker": scene.nodes[sender].worker,
                                "egress_interface": interface_name(scene.experiment, target.link_id, sender),
                                **values.to_dict(),
                            })
                    result["snapshots"].append({
                        "index": snapshot.index, "sim_time_ms": snapshot.sim_time_ms,
                        "digest": snapshot.digest,
                        "modeled_links": sorted(covered),
                        "unmodeled_links": sorted(set(scene.links_by_id) - covered),
                        "states": entries,
                    })
                print(json.dumps(result, indent=2, sort_keys=True))
                return 0
            profile = load_channel_profile(args.profile, scene)
            states = build_channel_states(scene, profile)
            modeled = {state.link_id for state in states}
            result = {
                "scene_digest": profile.scene_digest,
                "channel_profile_digest": profile.digest,
                "revision": profile.revision,
                "modeled_links": sorted(modeled),
                "unmodeled_links": sorted(set(scene.links_by_id) - modeled),
                "states": [
                    {
                        "link_id": state.link_id,
                        "direction": state.direction,
                        "available": state.available,
                        "bandwidth_mbps": state.bandwidth_mbps,
                        "delay_ms": state.delay_ms,
                        "jitter_ms": state.jitter_ms,
                        "loss_pct": state.loss_pct,
                        "effective_time": state.effective_time.isoformat(),
                        "version": state.version,
                    }
                    for state in states
                ],
            }
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
        topology = build_topology(scene)
        routes = build_routes(scene, topology)
        neighbors = build_static_neighbors(scene)
        interfaces = planned_interface_names(scene)
        if args.command == "validate":
            result = {
                "experiment": scene.experiment,
                "scene_digest": scene_fingerprint(scene),
                "workers": list(scene.workers),
                "hosts": len(scene.hosts),
                "switches": len(scene.switches),
                "links": len(scene.links),
                "logical_routes": len(routes),
                "static_neighbor_entries": len(neighbors),
            }
        else:
            worker = plan_worker(scene, args.worker)
            local_switches = {switch.id for switch in worker.switches}
            local_hosts = {host.id for host in worker.hosts}
            result = {
                "experiment": scene.experiment,
                "worker": worker.worker_id,
                "scene_digest": worker.scene_digest,
                "hosts": [host.id for host in worker.hosts],
                "switches": [switch.id for switch in worker.switches],
                "local_links": [link.id for link in worker.local_links],
                "boundary_links": [link.id for link in worker.boundary_links],
                "logical_routes": [
                    {
                        "switch": route.switch_id,
                        "destination_host": route.destination_host,
                        "destination_ip": str(route.destination_ip),
                        "output_link": route.output_link,
                        "next_node": route.next_node,
                    }
                    for route in routes
                    if route.switch_id in local_switches
                ],
                "static_neighbor_entries": sum(
                    1 for entry in neighbors if entry.source_host in local_hosts
                ),
                "interfaces": {
                    f"{link_id}:{node_id}": name
                    for (link_id, node_id), name in sorted(interfaces.items())
                    if node_id in worker.node_ids
                },
            }
            if args.deployment:
                deployment = load_deployment(args.deployment, scene)
                result["vxlan_tunnels"] = [
                    {"link": tunnel.link_id, "switch": tunnel.switch_id,
                     "port": tunnel.port_name, "local_ip": str(tunnel.local_ip),
                     "remote_ip": str(tunnel.remote_ip), "vni": tunnel.vni}
                    for tunnel in plan_tunnels(scene, deployment, args.worker)
                ]
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (SceneError, RuntimeError) as exc:
        print(f"md-mininet: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
