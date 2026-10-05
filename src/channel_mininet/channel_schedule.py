"""Validated, controller-owned timeline of network emulation targets.

``netem_delay_ms`` is an *additional* egress delay.  It must not be confused
with the propagation-only ``ChannelState.delay_ms`` in the older model.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
from typing import Any, Mapping

from channel_mininet.schema import Scene, SceneError, scene_fingerprint


def netem_delay_ns(delay_ms: float) -> int:
    """Quantize a sourced millisecond target to tc's integer nanoseconds."""
    return int((Decimal(str(delay_ms)) * Decimal(1_000_000)).to_integral_value(
        rounding=ROUND_HALF_UP
    ))


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256(encoded.encode("utf-8")).hexdigest()


def _object(value: Any, label: str, fields: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise SceneError(f"{label} must be an object")
    unknown = set(value) - fields
    if unknown:
        raise SceneError(f"{label} has unknown fields: {', '.join(sorted(unknown))}")
    return value


def _number(value: Any, label: str, *, positive: bool = False) -> float:
    if type(value) not in (int, float):
        raise SceneError(f"{label} must be a finite number")
    try:
        result = float(value)
    except OverflowError as exc:
        raise SceneError(f"{label} must be a finite number") from exc
    if not isfinite(result) or result < 0 or (positive and result == 0):
        raise SceneError(f"{label} must be {'positive' if positive else 'nonnegative'} and finite")
    return result


@dataclass(frozen=True, slots=True)
class DirectionTarget:
    bandwidth_mbps: float
    netem_delay_ms: float
    source: Mapping[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {"bandwidth_mbps": self.bandwidth_mbps,
                "netem_delay_ms": self.netem_delay_ms, "source": dict(self.source)}


@dataclass(frozen=True, slots=True)
class LinkTarget:
    link_id: str
    a_to_b: DirectionTarget
    b_to_a: DirectionTarget

    def to_dict(self) -> dict[str, Any]:
        return {"link_id": self.link_id, "a_to_b": self.a_to_b.to_dict(),
                "b_to_a": self.b_to_a.to_dict()}


@dataclass(frozen=True, slots=True)
class Snapshot:
    index: int
    sim_time_ms: int
    links: tuple[LinkTarget, ...]
    digest: str

    def to_dict(self) -> dict[str, Any]:
        return {"index": self.index, "sim_time_ms": self.sim_time_ms,
                "links": [link.to_dict() for link in self.links], "digest": self.digest}


@dataclass(frozen=True, slots=True)
class ChannelSchedule:
    scene_digest: str
    revision: int
    snapshots: tuple[Snapshot, ...]
    digest: str


def _source(value: Any, label: str) -> Mapping[str, str]:
    raw = _object(value, label, {"kind", "reference", "recorded_at"})
    kind = raw.get("kind")
    if kind not in ("measurement", "simulation", "scenario_assumption"):
        raise SceneError(f"{label}.kind must be measurement, simulation, or scenario_assumption")
    reference = raw.get("reference")
    if not isinstance(reference, str) or not reference.strip():
        raise SceneError(f"{label}.reference must be a nonempty string")
    recorded_at = raw.get("recorded_at")
    if not isinstance(recorded_at, str):
        raise SceneError(f"{label}.recorded_at must be a timestamp with UTC offset")
    try:
        parsed = datetime.fromisoformat(recorded_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SceneError(f"{label}.recorded_at is not ISO 8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SceneError(f"{label}.recorded_at must include a UTC offset")
    return {"kind": kind, "reference": reference.strip(), "recorded_at": recorded_at}


def _direction(value: Any, label: str) -> DirectionTarget:
    raw = _object(value, label, {"bandwidth_mbps", "netem_delay_ms", "source"})
    bandwidth = _number(raw.get("bandwidth_mbps"), f"{label}.bandwidth_mbps", positive=True)
    delay = _number(raw.get("netem_delay_ms"), f"{label}.netem_delay_ms")
    if bandwidth < 0.000001:
        raise SceneError(f"{label}.bandwidth_mbps is below one bit/s")
    if bandwidth * 1_000_000 > 2**63 - 1:
        raise SceneError(f"{label}.bandwidth_mbps exceeds supported bit rate")
    if delay > (2**63 - 1) / 1_000_000:
        raise SceneError(f"{label}.netem_delay_ms exceeds supported delay")
    if delay > 0 and netem_delay_ns(delay) == 0:
        raise SceneError(f"{label}.netem_delay_ms rounds to zero nanoseconds")
    return DirectionTarget(
        bandwidth_mbps=bandwidth,
        netem_delay_ms=delay,
        source=_source(raw.get("source"), f"{label}.source"),
    )


def parse_snapshot(value: Any, scene: Scene, index: int) -> Snapshot:
    """Parse a file or wire snapshot.  A wire snapshot includes its digest."""
    label = f"snapshots[{index}]"
    raw = _object(value, label, {"index", "sim_time_ms", "links", "digest"})
    if "index" in raw and (type(raw["index"]) is not int or raw["index"] != index):
        raise SceneError(f"{label}.index must be {index}")
    time_ms = raw.get("sim_time_ms")
    if type(time_ms) is not int or time_ms < 0:
        raise SceneError(f"{label}.sim_time_ms must be a nonnegative integer")
    link_items = raw.get("links")
    if not isinstance(link_items, list):
        raise SceneError(f"{label}.links must be a list")
    links: dict[str, LinkTarget] = {}
    for position, value in enumerate(link_items):
        item_label = f"{label}.links[{position}]"
        link = _object(value, item_label, {"link_id", "a_to_b", "b_to_a"})
        link_id = link.get("link_id")
        if not isinstance(link_id, str) or link_id not in scene.links_by_id:
            raise SceneError(f"{item_label}.link_id must name a scene link")
        if link_id in links:
            raise SceneError(f"{label} contains duplicate link {link_id!r}")
        links[link_id] = LinkTarget(
            link_id, _direction(link.get("a_to_b"), f"{item_label}.a_to_b"),
            _direction(link.get("b_to_a"), f"{item_label}.b_to_a"),
        )
    canonical = {"index": index, "sim_time_ms": time_ms,
                 "links": [links[key].to_dict() for key in sorted(links)]}
    digest = _digest(canonical)
    if "digest" in raw and raw["digest"] != digest:
        raise SceneError(f"{label}.digest does not match snapshot contents")
    return Snapshot(index, time_ms, tuple(links[key] for key in sorted(links)), digest)


def schedule_from_dict(value: Any, scene: Scene) -> ChannelSchedule:
    raw = _object(value, "channel schedule", {"version", "scene_digest", "revision", "snapshots"})
    if type(raw.get("version")) is not int or raw["version"] != 2:
        raise SceneError("channel schedule version must be 2")
    scene_digest = scene_fingerprint(scene)
    if raw.get("scene_digest") != scene_digest:
        raise SceneError("channel schedule scene_digest does not match the scene")
    revision = raw.get("revision")
    if type(revision) is not int or revision < 1:
        raise SceneError("channel schedule revision must be a positive integer")
    items = raw.get("snapshots")
    if not isinstance(items, list) or not items:
        raise SceneError("channel schedule snapshots must be a nonempty list")
    snapshots = tuple(parse_snapshot(item, scene, index)
                      for index, item in enumerate(items))
    if snapshots[0].sim_time_ms != 0:
        raise SceneError("first channel snapshot must start at sim_time_ms=0")
    if any(b.sim_time_ms <= a.sim_time_ms for a, b in zip(snapshots, snapshots[1:])):
        raise SceneError("channel snapshot times must be strictly increasing")
    canonical = {"version": 2, "scene_digest": scene_digest, "revision": revision,
                 "snapshots": [snapshot.to_dict() for snapshot in snapshots]}
    return ChannelSchedule(scene_digest, revision, snapshots, _digest(canonical))


def load_channel_schedule(path: str | Path, scene: Scene) -> ChannelSchedule:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SceneError(f"cannot load channel schedule {path}: {exc}") from exc
    return schedule_from_dict(value, scene)
