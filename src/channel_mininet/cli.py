"""Scene inspection and foreground basic Mininet startup commands."""

from __future__ import annotations

import argparse
import json
import sys

from channel_mininet.control.neighbors import build_static_neighbors
from channel_mininet.control.routing import build_routes
from channel_mininet.runtime.names import planned_interface_names
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
    up = commands.add_parser("up", help="start the basic Mininet network in the foreground")
    up.add_argument("scene")
    scope = up.add_mutually_exclusive_group(required=True)
    scope.add_argument("--worker", help="start one worker's local partition")
    scope.add_argument(
        "--all-workers", action="store_true", help="start all partitions on this machine"
    )
    up.add_argument("--controller-host", help="IPv4 address of an independently running controller")
    up.add_argument("--controller-port", type=int)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        scene = load_scene(args.scene)
        if args.command == "up":
            if args.controller_host is None and args.controller_port is not None:
                raise SceneError("--controller-port requires --controller-host")
            run_basic_network(
                scene,
                None if args.all_workers else args.worker,
                controller_host=args.controller_host,
                controller_port=6653 if args.controller_port is None else args.controller_port,
            )
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
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (SceneError, RuntimeError) as exc:
        print(f"md-mininet: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
