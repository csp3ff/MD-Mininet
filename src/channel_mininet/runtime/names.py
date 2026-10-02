"""Stable names for resources created by an experiment."""

from __future__ import annotations

from hashlib import blake2s

from channel_mininet.schema import Scene, SceneError


def container_name(experiment: str, node_id: str) -> str:
    return f"md-{experiment}-{node_id}"


def interface_name(experiment: str, link_id: str, node_id: str) -> str:
    """Return a deterministic Linux interface name within the 15-byte limit."""

    identity = f"{experiment}\0{link_id}\0{node_id}".encode("utf-8")
    return "m" + blake2s(identity, digest_size=7).hexdigest()


def planned_interface_names(scene: Scene) -> dict[tuple[str, str], str]:
    """Detect the exceptionally unlikely hash collision before deployment."""

    result: dict[tuple[str, str], str] = {}
    reverse: dict[str, tuple[str, str]] = {}
    for link in scene.links:
        for node_id in (link.a, link.b):
            key = (link.id, node_id)
            name = interface_name(scene.experiment, *key)
            if name in reverse and reverse[name] != key:
                raise SceneError(f"interface name collision: {key} and {reverse[name]}")
            result[key] = name
            reverse[name] = key
    return result
