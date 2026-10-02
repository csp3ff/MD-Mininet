"""Versioned, deployment-independent scene definitions.

The first version has one IPv4 subnet spanning all worker partitions. A
worker partition is not an IP routing domain. No dynamic link state is applied
by this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from ipaddress import IPv4Address, IPv4Network, ip_address, ip_network
import json
from pathlib import Path
import re
from typing import Any, Literal, Mapping


_ID = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
_MAC = re.compile(r"^(?:[0-9a-f]{2}:){5}[0-9a-f]{2}$")
_DPID = re.compile(r"^[0-9a-f]{16}$")


class SceneError(ValueError):
    """A scene is malformed or incompatible with the first version."""


@dataclass(frozen=True, slots=True)
class Host:
    id: str
    worker: str
    ip: IPv4Address
    mac: str


@dataclass(frozen=True, slots=True)
class Switch:
    id: str
    worker: str
    dpid: str


Node = Host | Switch


@dataclass(frozen=True, slots=True)
class Link:
    id: str
    a: str
    b: str

    def other(self, node_id: str) -> str:
        if node_id == self.a:
            return self.b
        if node_id == self.b:
            return self.a
        raise SceneError(f"node {node_id!r} is not on link {self.id!r}")


@dataclass(frozen=True, slots=True)
class ChannelState:
    """Reserved directional link state; the static runtime does not consume it."""

    link_id: str
    direction: Literal["a_to_b", "b_to_a"]
    available: bool
    bandwidth_mbps: float | None
    delay_ms: float | None
    jitter_ms: float | None
    loss_pct: float | None
    effective_time: datetime
    version: int


@dataclass(frozen=True, slots=True)
class Scene:
    version: int
    experiment: str
    subnet: IPv4Network
    workers: tuple[str, ...]
    hosts: tuple[Host, ...]
    switches: tuple[Switch, ...]
    links: tuple[Link, ...]

    @property
    def nodes(self) -> dict[str, Node]:
        return {node.id: node for node in (*self.hosts, *self.switches)}

    @property
    def links_by_id(self) -> dict[str, Link]:
        return {link.id: link for link in self.links}

    def validate(self) -> None:
        if self.version != 1:
            raise SceneError(f"unsupported scene version: {self.version}")
        _check_id(self.experiment, "experiment")
        if not self.workers:
            raise SceneError("workers must be a nonempty list of unique IDs")
        for worker in self.workers:
            _check_id(worker, "worker")
        if len(self.workers) != len(set(self.workers)):
            raise SceneError("workers must be a nonempty list of unique IDs")
        if not self.hosts or not self.switches:
            raise SceneError("at least one host and one switch are required")

        nodes: dict[str, Node] = {}
        for node in (*self.hosts, *self.switches):
            _check_id(node.id, "node")
            if node.id in nodes:
                raise SceneError(f"duplicate node ID: {node.id}")
            if node.worker not in self.workers:
                raise SceneError(f"unknown worker {node.worker!r} for {node.id!r}")
            nodes[node.id] = node
        for worker in self.workers:
            if not any(s.worker == worker for s in self.switches):
                raise SceneError(f"worker {worker!r} needs at least one switch")

        ips: set[IPv4Address] = set()
        macs: set[str] = set()
        for host in self.hosts:
            if host.ip not in self.subnet or host.ip in (self.subnet.network_address, self.subnet.broadcast_address):
                raise SceneError(f"host {host.id!r} IP is not usable in {self.subnet}")
            if host.ip in ips:
                raise SceneError(f"duplicate host IP: {host.ip}")
            ips.add(host.ip)
            if not isinstance(host.mac, str) or not _MAC.fullmatch(host.mac) or int(host.mac[:2], 16) & 1:
                raise SceneError(f"invalid unicast MAC for host {host.id!r}: {host.mac}")
            if host.mac in macs:
                raise SceneError(f"duplicate host MAC: {host.mac}")
            macs.add(host.mac)

        dpids: set[str] = set()
        for switch in self.switches:
            if not isinstance(switch.dpid, str) or not _DPID.fullmatch(switch.dpid):
                raise SceneError(f"switch {switch.id!r} DPID must be 16 lowercase hex digits")
            if switch.dpid in dpids:
                raise SceneError(f"duplicate DPID: {switch.dpid}")
            dpids.add(switch.dpid)

        link_ids: set[str] = set()
        endpoint_pairs: set[frozenset[str]] = set()
        host_degree = {host.id: 0 for host in self.hosts}
        for link in self.links:
            _check_id(link.id, "link")
            _check_id(link.a, "link endpoint")
            _check_id(link.b, "link endpoint")
            if link.id in link_ids:
                raise SceneError(f"duplicate link ID: {link.id}")
            link_ids.add(link.id)
            if link.a == link.b or link.a not in nodes or link.b not in nodes:
                raise SceneError(f"invalid endpoints for link {link.id!r}")
            pair = frozenset((link.a, link.b))
            if pair in endpoint_pairs:
                raise SceneError(f"parallel links are unsupported: {link.a}, {link.b}")
            endpoint_pairs.add(pair)
            a, b = nodes[link.a], nodes[link.b]
            if isinstance(a, Host) and isinstance(b, Host):
                raise SceneError(f"host-to-host link is unsupported: {link.id}")
            if a.worker != b.worker and (isinstance(a, Host) or isinstance(b, Host)):
                raise SceneError(f"cross-worker link must join switches: {link.id}")
            if isinstance(a, Host):
                host_degree[a.id] += 1
            if isinstance(b, Host):
                host_degree[b.id] += 1
        for host_id, degree in host_degree.items():
            if degree != 1:
                raise SceneError(f"host {host_id!r} must have exactly one business link; got {degree}")


def scene_fingerprint(scene: Scene) -> str:
    """Canonical scene digest for future coordinator/worker consistency checks."""

    canonical = {
        "version": scene.version,
        "experiment": scene.experiment,
        "subnet": str(scene.subnet),
        "workers": sorted(scene.workers),
        "hosts": [
            {"id": host.id, "worker": host.worker, "ip": str(host.ip), "mac": host.mac}
            for host in sorted(scene.hosts, key=lambda item: item.id)
        ],
        "switches": [
            {"id": switch.id, "worker": switch.worker, "dpid": switch.dpid}
            for switch in sorted(scene.switches, key=lambda item: item.id)
        ],
        "links": [
            {"id": link.id, "a": link.a, "b": link.b}
            for link in sorted(scene.links, key=lambda item: item.id)
        ],
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()


def _check_id(value: str, kind: str) -> None:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise SceneError(f"invalid {kind} ID: {value!r}")


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SceneError(f"{name} must be an object")
    return value


def _list(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise SceneError(f"{name} must be a list")
    return value


def scene_from_dict(data: Mapping[str, Any]) -> Scene:
    """Parse and validate JSON-like data without touching the runtime."""

    data = _mapping(data, "scene")
    try:
        version = data["version"]
        if type(version) is not int:
            raise SceneError("version must be an integer")
        subnet = ip_network(data["subnet"], strict=True)
        if not isinstance(subnet, IPv4Network):
            raise SceneError("only IPv4 is supported")
        hosts = tuple(
            Host(
                id=item["id"],
                worker=item["worker"],
                ip=ip_address(item["ip"]),
                mac=item["mac"],
            )
            for raw in _list(data["hosts"], "hosts")
            for item in (_mapping(raw, "host"),)
        )
        switches = tuple(
            Switch(id=item["id"], worker=item["worker"], dpid=item["dpid"])
            for raw in _list(data["switches"], "switches")
            for item in (_mapping(raw, "switch"),)
        )
        links = tuple(
            Link(id=item["id"], a=item["a"], b=item["b"])
            for raw in _list(data["links"], "links")
            for item in (_mapping(raw, "link"),)
        )
        scene = Scene(
            version=version,
            experiment=data["experiment"],
            subnet=subnet,
            workers=tuple(_list(data["workers"], "workers")),
            hosts=hosts,
            switches=switches,
            links=links,
        )
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, SceneError):
            raise
        raise SceneError(f"malformed scene: {exc}") from exc
    if not all(isinstance(host.ip, IPv4Address) for host in scene.hosts):
        raise SceneError("only IPv4 host addresses are supported")
    scene.validate()
    return scene


def load_scene(path: str | Path) -> Scene:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SceneError(f"cannot load scene {path}: {exc}") from exc
    return scene_from_dict(data)
