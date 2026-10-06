"""Resolve files belonging to a scene directory, while accepting legacy JSON paths."""

from __future__ import annotations

from pathlib import Path

from channel_mininet.schema import SceneError


def scene_file(value: str | Path) -> Path:
    path = Path(value).expanduser().resolve()
    if path.is_dir():
        path = path / "workers.json"
    if not path.is_file():
        raise SceneError(f"scene file not found: {path}")
    return path


def bundled_file(value: str | Path, explicit: str | Path | None, name: str) -> Path | None:
    if explicit is not None:
        return Path(explicit).expanduser().resolve()
    directory = Path(value).expanduser().resolve()
    if directory.is_dir():
        candidate = directory / name
        if not candidate.is_file():
            raise SceneError(f"scene directory is missing {name}: {candidate}")
        return candidate
    return None
