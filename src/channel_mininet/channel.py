"""Pure, medium-independent planning of one static directional snapshot.

Profiles describe reference devices, not the veth/OVS interfaces that happen
to run the emulation. This module never touches Mininet or the host network.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
from math import isclose, isfinite
from pathlib import Path
from typing import Any, Literal, Mapping

from channel_mininet.schema import ChannelState, Scene, SceneError, scene_fingerprint


Direction = Literal["a_to_b", "b_to_a"]
SourceKind = Literal["device_readout", "field_measurement", "datasheet"]
SPEED_OF_LIGHT_MPS = 299_792_458.0


@dataclass(frozen=True, slots=True)
class SourceRecord:
    kind: SourceKind
    reference: str
    device_model: str
    recorded_at: datetime


@dataclass(frozen=True, slots=True)
class PortProfile:
    link_id: str
    node_id: str
    port_type: str
    rate_mbps: float
    source: SourceRecord


@dataclass(frozen=True, slots=True)
class LinkEvidence:
    kind: Literal["measurement", "datasheet", "scenario_assumption"]
    reference: str
    recorded_at: datetime


@dataclass(frozen=True, slots=True)
class DirectionProfile:
    link_id: str
    direction: Direction
    available: bool
    nominal_bandwidth_mbps: float
    distance_m: float
    max_distance_m: float | None
    propagation_speed_mps: float
    velocity_factor_of_c: float | None
    jitter_ms: float | None
    loss_pct: float | None
    source: LinkEvidence


@dataclass(frozen=True, slots=True)
class ChannelProfile:
    scene_digest: str
    revision: int
    effective_time: datetime
    ports: tuple[PortProfile, ...]
    directions: tuple[DirectionProfile, ...]
    digest: str


def _object(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SceneError(f"{label} must be an object")
    return value


def _items(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise SceneError(f"{label} must be a list")
    return value


def _fields(item: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unknown = set(item) - allowed
    if unknown:
        raise SceneError(f"{label} has unknown fields: {', '.join(sorted(unknown))}")


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SceneError(f"{label} must be a nonempty string")
    return value.strip()


def _number(value: Any, label: str, *, positive: bool = False) -> float:
    if type(value) not in (int, float):
        raise SceneError(f"{label} must be a finite number")
    try:
        number = float(value)
    except OverflowError as exc:
        raise SceneError(f"{label} must be a finite number") from exc
    if not isfinite(number):
        raise SceneError(f"{label} must be a finite number")
    if (positive and number <= 0) or (not positive and number < 0):
        raise SceneError(f"{label} must be {'positive' if positive else 'nonnegative'}")
    return number


def _optional_number(value: Any, label: str) -> float | None:
    return None if value is None else _number(value, label)


def _time(value: Any, label: str) -> datetime:
    raw = _string(value, label)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SceneError(f"{label} must be an ISO 8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SceneError(f"{label} must include a UTC offset")
    return parsed


def _source(value: Any, label: str) -> SourceRecord:
    item = _object(value, label)
    _fields(item, {"kind", "reference", "device_model", "recorded_at"}, label)
    kind = _string(item.get("kind"), f"{label}.kind")
    if kind not in ("device_readout", "field_measurement", "datasheet"):
        raise SceneError(f"{label}.kind must be device_readout, field_measurement, or datasheet")
    return SourceRecord(
        kind=kind,
        reference=_string(item.get("reference"), f"{label}.reference"),
        device_model=_string(item.get("device_model"), f"{label}.device_model"),
        recorded_at=_time(item.get("recorded_at"), f"{label}.recorded_at"),
    )


def _link_source(value: Any, label: str) -> LinkEvidence:
    item = _object(value, label)
    _fields(item, {"kind", "reference", "recorded_at"}, label)
    kind = _string(item.get("kind"), f"{label}.kind")
    if kind not in ("measurement", "datasheet", "scenario_assumption"):
        raise SceneError(f"{label}.kind must be measurement, datasheet, or scenario_assumption")
    return LinkEvidence(
        kind=kind,
        reference=_string(item.get("reference"), f"{label}.reference"),
        recorded_at=_time(item.get("recorded_at"), f"{label}.recorded_at"),
    )


def profile_from_dict(data: Mapping[str, Any], scene: Scene) -> ChannelProfile:
    """Validate a partial channel profile against an existing scene."""

    data = _object(data, "channel profile")
    _fields(
        data,
        {"version", "scene_digest", "revision", "effective_time", "ports", "links"},
        "channel profile",
    )
    if type(data.get("version")) is not int or data["version"] != 1:
        raise SceneError("channel profile version must be 1")
    digest = scene_fingerprint(scene)
    if data.get("scene_digest") != digest:
        raise SceneError("channel profile scene_digest does not match the scene")
    revision = data.get("revision")
    if type(revision) is not int or revision < 1:
        raise SceneError("channel profile revision must be a positive integer")
    effective_time = _time(data.get("effective_time"), "effective_time")

    known_links = scene.links_by_id
    ports: dict[tuple[str, str], PortProfile] = {}
    for index, raw in enumerate(_items(data.get("ports"), "ports")):
        label = f"ports[{index}]"
        item = _object(raw, label)
        _fields(item, {"link_id", "node_id", "port_type", "rate_mbps", "source"}, label)
        link_id = _string(item.get("link_id"), f"{label}.link_id")
        node_id = _string(item.get("node_id"), f"{label}.node_id")
        link = known_links.get(link_id)
        if link is None or node_id not in (link.a, link.b):
            raise SceneError(f"{label} must name an endpoint of a scene link")
        key = (link_id, node_id)
        if key in ports:
            raise SceneError(f"duplicate channel port {key!r}")
        ports[key] = PortProfile(
            link_id=link_id,
            node_id=node_id,
            port_type=_string(item.get("port_type"), f"{label}.port_type"),
            rate_mbps=_number(item.get("rate_mbps"), f"{label}.rate_mbps", positive=True),
            source=_source(item.get("source"), f"{label}.source"),
        )

    directions: dict[tuple[str, Direction], DirectionProfile] = {}
    for index, raw in enumerate(_items(data.get("links"), "links")):
        label = f"links[{index}]"
        item = _object(raw, label)
        _fields(item, {"link_id", "model", "a_to_b", "b_to_a"}, label)
        link_id = _string(item.get("link_id"), f"{label}.link_id")
        if link_id not in known_links:
            raise SceneError(f"{label} names an unknown scene link")
        if item.get("model") != "generic":
            raise SceneError(f"{label}.model must be generic")
        for direction in ("a_to_b", "b_to_a"):
            raw_direction = _object(item.get(direction), f"{label}.{direction}")
            _fields(
                raw_direction,
                {"available", "nominal_bandwidth_mbps", "distance_m", "max_distance_m",
                 "propagation_speed_mps", "velocity_factor_of_c", "jitter_ms", "loss_pct", "source"},
                f"{label}.{direction}",
            )
            key = (link_id, direction)
            if key in directions:
                raise SceneError(f"duplicate channel direction {key!r}")
            available = raw_direction.get("available")
            if type(available) is not bool:
                raise SceneError(f"{label}.{direction}.available must be a boolean")
            distance = _number(raw_direction.get("distance_m"), f"{label}.{direction}.distance_m")
            raw_max_distance = raw_direction.get("max_distance_m")
            max_distance = (
                None if raw_max_distance is None else
                _number(raw_max_distance, f"{label}.{direction}.max_distance_m", positive=True)
            )
            if max_distance is not None and distance > max_distance:
                raise SceneError(f"{label}.{direction}.distance_m exceeds max_distance_m")
            speed = _number(
                raw_direction.get("propagation_speed_mps"),
                f"{label}.{direction}.propagation_speed_mps",
                positive=True,
            )
            if speed > SPEED_OF_LIGHT_MPS:
                raise SceneError(f"{label}.{direction}.propagation_speed_mps must not exceed vacuum light speed")
            raw_velocity_factor = raw_direction.get("velocity_factor_of_c")
            velocity_factor = (
                None if raw_velocity_factor is None else
                _number(raw_velocity_factor, f"{label}.{direction}.velocity_factor_of_c", positive=True)
            )
            if velocity_factor is not None:
                if velocity_factor > 1:
                    raise SceneError(f"{label}.{direction}.velocity_factor_of_c must not exceed 1")
                if not isclose(speed, velocity_factor * SPEED_OF_LIGHT_MPS, rel_tol=1e-9):
                    raise SceneError(
                        f"{label}.{direction}.propagation_speed_mps does not match velocity_factor_of_c"
                    )
            loss = _optional_number(raw_direction.get("loss_pct"), f"{label}.{direction}.loss_pct")
            if loss is not None and loss > 100:
                raise SceneError(f"{label}.{direction}.loss_pct must not exceed 100")
            nominal_bandwidth = _number(
                raw_direction.get("nominal_bandwidth_mbps"),
                f"{label}.{direction}.nominal_bandwidth_mbps", positive=True,
            )
            directions[key] = DirectionProfile(
                link_id=link_id,
                direction=direction,
                available=available,
                nominal_bandwidth_mbps=nominal_bandwidth,
                distance_m=distance,
                max_distance_m=max_distance,
                propagation_speed_mps=speed,
                velocity_factor_of_c=velocity_factor,
                jitter_ms=_optional_number(raw_direction.get("jitter_ms"), f"{label}.{direction}.jitter_ms"),
                loss_pct=loss,
                source=_link_source(raw_direction.get("source"), f"{label}.{direction}.source"),
            )

    modeled_links = {link_id for link_id, _ in directions}
    for link_id in modeled_links:
        link = known_links[link_id]
        for node_id in (link.a, link.b):
            if (link_id, node_id) not in ports:
                raise SceneError(f"modeled link {link_id!r} is missing sourced port data for {node_id!r}")
        endpoint_limit = min(ports[(link_id, link.a)].rate_mbps, ports[(link_id, link.b)].rate_mbps)
        for direction in ("a_to_b", "b_to_a"):
            nominal = directions[(link_id, direction)].nominal_bandwidth_mbps
            if nominal > endpoint_limit:
                raise SceneError(
                    f"{link_id!r} {direction} nominal_bandwidth_mbps {nominal:g} "
                    f"exceeds endpoint rate limit {endpoint_limit:g} Mb/s"
                )
    for link_id, node_id in ports:
        if link_id not in modeled_links:
            raise SceneError(f"port data for {node_id!r} on unmodeled link {link_id!r}")

    encoded = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return ChannelProfile(
        scene_digest=digest,
        revision=revision,
        effective_time=effective_time,
        ports=tuple(ports[key] for key in sorted(ports)),
        directions=tuple(directions[key] for key in sorted(directions)),
        digest=sha256(encoded).hexdigest(),
    )


def load_channel_profile(path: str | Path, scene: Scene) -> ChannelProfile:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SceneError(f"cannot load channel profile {path}: {exc}") from exc
    return profile_from_dict(raw, scene)


def build_channel_states(scene: Scene, profile: ChannelProfile) -> tuple[ChannelState, ...]:
    """Compute one snapshot for each configured link's two directions."""

    if profile.scene_digest != scene_fingerprint(scene):
        raise SceneError("channel profile does not match the scene")
    ports = {(port.link_id, port.node_id): port for port in profile.ports}
    states = []
    for direction in profile.directions:
        link = scene.links_by_id[direction.link_id]
        sender, receiver = (link.a, link.b) if direction.direction == "a_to_b" else (link.b, link.a)
        rate = min(
            ports[(link.id, sender)].rate_mbps,
            ports[(link.id, receiver)].rate_mbps,
            direction.nominal_bandwidth_mbps,
        )
        delay = 1000 * direction.distance_m / direction.propagation_speed_mps
        if not isfinite(delay):
            raise SceneError(f"computed delay is not finite for {link.id!r} {direction.direction}")
        states.append(ChannelState(
            link_id=link.id,
            direction=direction.direction,
            available=direction.available,
            bandwidth_mbps=rate if direction.available else None,
            delay_ms=delay if direction.available else None,
            jitter_ms=direction.jitter_ms if direction.available else None,
            loss_pct=direction.loss_pct if direction.available else None,
            effective_time=profile.effective_time,
            version=profile.revision,
        ))
    return tuple(states)
