"""Create a self-contained scene directory from a topology or a random tree."""

from __future__ import annotations

from datetime import datetime, timezone
from ipaddress import ip_network, IPv4Network
from itertools import islice
import json
from pathlib import Path
import random

import yaml

from channel_mininet.channel_schedule import load_channel_schedule, schedule_from_dict
from channel_mininet.runtime.deployment import _ipv4
from channel_mininet.scene_bundle import scene_file
from channel_mininet.schema import SceneError, load_scene, scene_fingerprint, scene_from_dict


def _random_topology(args: object, worker_ids: list[str]) -> dict:
    if args.hosts_per_worker < 1 or args.switches_per_worker < 1:
        raise SceneError("random topology needs at least one host and switch per worker")
    try:
        subnet = ip_network(args.subnet, strict=True)
    except ValueError as exc:
        raise SceneError(f"invalid subnet: {exc}") from exc
    if not isinstance(subnet, IPv4Network):
        raise SceneError("random topology requires an IPv4 subnet")
    host_count = len(worker_ids) * args.hosts_per_worker
    addresses = list(islice(subnet.hosts(), host_count))
    if len(addresses) != host_count:
        raise SceneError("subnet does not have enough usable host addresses")
    rng = random.Random(args.seed)
    topology = {
        "version": 1, "experiment": args.experiment, "subnet": str(subnet),
        "workers": worker_ids, "hosts": [], "switches": [], "links": [],
    }
    switches_by_worker = {}
    for worker_id in worker_ids:
        local = []
        for _ in range(args.switches_per_worker):
            number = len(topology["switches"]) + 1
            switch_id = f"s{number}"
            topology["switches"].append({
                "id": switch_id, "worker": worker_id, "dpid": f"{number:016x}",
            })
            local.append(switch_id)
        switches_by_worker[worker_id] = local
    for index, address in enumerate(addresses, start=1):
        worker_id = worker_ids[(index - 1) // args.hosts_per_worker]
        host_id = f"h{index}"
        topology["hosts"].append({
            "id": host_id, "worker": worker_id, "ip": str(address),
            "mac": "02:77:" + ":".join(f"{(index >> shift) & 255:02x}" for shift in (24, 16, 8, 0)),
        })
        topology["links"].append({
            "id": f"l{len(topology['links']) + 1}", "a": host_id,
            "b": rng.choice(switches_by_worker[worker_id]),
        })
    ordered_switches = [switch for worker in worker_ids for switch in switches_by_worker[worker]]
    for left, right in zip(ordered_switches, ordered_switches[1:]):
        topology["links"].append({
            "id": f"l{len(topology['links']) + 1}", "a": left, "b": right,
        })
    scene_from_dict(topology)
    return topology


def generate_scene(args: object) -> None:
    output = Path(args.output).expanduser().resolve()
    if output.exists():
        raise SceneError(f"output already exists: {output}")
    if not 1 <= args.controller_port <= 65535 or not 1 <= args.channel_control_port <= 65535:
        raise SceneError("controller ports must be between 1 and 65535")
    if args.controller_port == args.channel_control_port:
        raise SceneError("controller and channel ports must differ")
    workers = {}
    for entry in args.worker_ip:
        worker_id, separator, address = entry.partition("=")
        if not separator or worker_id in workers:
            raise SceneError(f"--worker-ip must be a unique ID=IPv4 pair: {entry!r}")
        workers[worker_id] = str(_ipv4(address, f"worker {worker_id!r} underlay"))
    if len(set(workers.values())) != len(workers):
        raise SceneError("worker underlay addresses must be unique")
    if args.command == "generate-random-scene":
        topology = _random_topology(args, list(workers))
        scene = scene_from_dict(topology)
    else:
        source_path = scene_file(args.source)
        scene = load_scene(source_path)
        if set(workers) != set(scene.workers):
            raise SceneError("--worker-ip IDs must match topology workers exactly")
        topology = json.loads(source_path.read_text(encoding="utf-8"))
    controller_host = str(_ipv4(args.controller_host, "controller host"))
    recorded_at = args.recorded_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        parsed_at = datetime.fromisoformat(recorded_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SceneError("--recorded-at must be ISO 8601 with UTC offset") from exc
    if parsed_at.tzinfo is None or parsed_at.utcoffset() is None:
        raise SceneError("--recorded-at must include a UTC offset")

    rng = random.Random(args.seed)
    retained = {}
    if getattr(args, "base_channel", None):
        original = load_channel_schedule(args.base_channel, scene)
        if len(original.snapshots) != 1 or original.snapshots[0].sim_time_ms != 0:
            raise SceneError("--base-channel must contain one snapshot at sim_time_ms=0")
        retained = {link.link_id: link.to_dict() for link in original.snapshots[0].links}
    reference = (
        f"Synthetic scenario assumption generated with seed {args.seed}; "
        "not a device specification or field measurement."
    )
    links = []
    for link in scene.links:
        if link.id in retained:
            links.append(retained[link.id])
            continue
        directions = {}
        for direction in ("a_to_b", "b_to_a"):
            directions[direction] = {
                "bandwidth_mbps": rng.choice((100, 250, 500, 1000)),
                "netem_delay_ms": round(rng.uniform(0.5, 5.0), 3),
                "source": {
                    "kind": "scenario_assumption",
                    "reference": reference,
                    "recorded_at": recorded_at,
                },
            }
        links.append({"link_id": link.id, **directions})
    channel = {
        "version": 2,
        "scene_digest": scene_fingerprint(scene),
        "revision": 1,
        "snapshots": [{"sim_time_ms": 0, "links": links}],
    }
    schedule_from_dict(channel, scene)
    deployment = {
        "version": 1,
        "scene_digest": scene_fingerprint(scene),
        "workers": workers,
        "controller": {
            "host": controller_host,
            "port": args.controller_port,
            "channel_port": args.channel_control_port,
        },
    }
    # Validate everything before creating the output directory.
    output.mkdir(parents=True)
    (output / "workers.json").write_text(
        json.dumps(topology, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (output / "deployment.yml").write_text(
        yaml.safe_dump(deployment, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    (output / "channel.json").write_text(
        json.dumps(channel, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"Generated {output} (scene_digest {scene_fingerprint(scene)})")
