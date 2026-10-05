"""Shared physical endpoints for a distributed Mininet scene."""

from __future__ import annotations

from dataclasses import dataclass
from ipaddress import IPv4Address, ip_address
import json
from pathlib import Path
from typing import Any

from channel_mininet.schema import Scene, SceneError, scene_fingerprint


@dataclass(frozen=True, slots=True)
class Deployment:
    scene_digest: str
    workers: dict[str, IPv4Address]
    controller_host: IPv4Address
    controller_port: int
    channel_port: int = 6654


def _ipv4(value: Any, label: str) -> IPv4Address:
    if not isinstance(value, str):
        raise SceneError(f"{label} must be an IPv4 address string")
    try:
        address = ip_address(value)
    except (TypeError, ValueError) as exc:
        raise SceneError(f"{label} must be an IPv4 address") from exc
    if (not isinstance(address, IPv4Address) or address.is_unspecified or
            address.is_multicast or address.is_loopback or address.is_link_local or
            address.is_reserved):
        raise SceneError(f"{label} must be a routable unicast IPv4 address")
    return address


def _read_deployment(path: Path) -> Any:
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SceneError(f"cannot read deployment {path}: {exc}") from exc

    suffix = path.suffix.lower()
    if suffix == ".json":
        try:
            return json.loads(source)
        except json.JSONDecodeError as exc:
            raise SceneError(f"invalid JSON deployment {path}: {exc}") from exc
    if suffix in (".yml", ".yaml"):
        try:
            import yaml
        except ImportError as exc:
            raise SceneError("YAML deployment requires PyYAML; reinstall the project") from exc
        try:
            return yaml.safe_load(source)
        except yaml.YAMLError as exc:
            raise SceneError(f"invalid YAML deployment {path}: {exc}") from exc
    raise SceneError("deployment file must end in .yml, .yaml, or .json")


def load_deployment(path: str | Path, scene: Scene) -> Deployment:
    """Validate that every scene worker has one unique underlay endpoint."""

    data = _read_deployment(Path(path))
    try:
        if not isinstance(data, dict):
            raise SceneError("deployment must be an object")
        if data["version"] != 1 or type(data["version"]) is not int:
            raise SceneError("unsupported deployment version")
        digest = data["scene_digest"]
        if digest != scene_fingerprint(scene):
            raise SceneError("deployment scene_digest does not match the scene")
        raw_workers = data["workers"]
        if not isinstance(raw_workers, dict) or set(raw_workers) != set(scene.workers):
            raise SceneError("deployment workers must match scene workers exactly")
        workers = {worker: _ipv4(address, f"worker {worker!r} underlay")
                   for worker, address in raw_workers.items()}
        if len(set(workers.values())) != len(workers):
            raise SceneError("worker underlay addresses must be unique")
        controller = data["controller"]
        if not isinstance(controller, dict):
            raise SceneError("controller must be an object")
        controller_host = _ipv4(controller["host"], "controller host")
        controller_port = controller["port"]
        if type(controller_port) is not int or not 1 <= controller_port <= 65535:
            raise SceneError("controller port must be between 1 and 65535")
        channel_port = controller.get("channel_port", 6654)
        if type(channel_port) is not int or not 1 <= channel_port <= 65535:
            raise SceneError("controller channel_port must be between 1 and 65535")
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, SceneError):
            raise
        raise SceneError(f"invalid deployment {path}: {exc}") from exc
    return Deployment(digest, workers, controller_host, controller_port, channel_port)
