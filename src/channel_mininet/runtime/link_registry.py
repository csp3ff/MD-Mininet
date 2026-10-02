"""Persist exact ownership and observed port numbers for local links.

This registry is a planning primitive. A future deployment backend must use
it for targeted cleanup; it must never call a global Mininet or OVS cleanup
command. The backend will need its own write-ahead record for crash recovery.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import tempfile

from channel_mininet.schema import SceneError


@dataclass(frozen=True, slots=True)
class LinkEndpoint:
    node_id: str
    interface_name: str
    ofport: int | None = None


@dataclass(frozen=True, slots=True)
class LinkRecord:
    link_id: str
    owner: str  # worker ID for an internal link, coordinator for a boundary link
    a: LinkEndpoint
    b: LinkEndpoint


class LinkRegistry:
    def __init__(self, path: str | Path, experiment: str):
        self.path = Path(path)
        self.experiment = experiment
        self.records: dict[str, LinkRecord] = {}

    def load(self) -> None:
        if not self.path.exists():
            self.records = {}
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if raw["version"] != 1 or raw["experiment"] != self.experiment:
                raise SceneError("link registry version or experiment does not match")
            records = {}
            for item in raw["links"]:
                record = LinkRecord(
                    link_id=item["link_id"],
                    owner=item["owner"],
                    a=LinkEndpoint(**item["a"]),
                    b=LinkEndpoint(**item["b"]),
                )
                if record.link_id in records:
                    raise SceneError(f"duplicate registry link: {record.link_id}")
                records[record.link_id] = record
        except (OSError, KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, SceneError):
                raise
            raise SceneError(f"invalid link registry {self.path}: {exc}") from exc
        self.records = records

    def put(self, record: LinkRecord) -> None:
        with self._locked():
            self.load()
            existing = self.records.get(record.link_id)
            if existing is not None and existing.owner != record.owner:
                raise SceneError(f"link {record.link_id!r} belongs to {existing.owner!r}")
            self.records[record.link_id] = record
            self._save_unlocked()

    def remove(self, link_id: str, owner: str) -> None:
        with self._locked():
            self.load()
            existing = self.records.get(link_id)
            if existing is None:
                return
            if existing.owner != owner:
                raise SceneError(f"link {link_id!r} belongs to {existing.owner!r}")
            del self.records[link_id]
            self._save_unlocked()

    @contextmanager
    def _locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_name(self.path.name + ".lock")
        with lock_path.open("a+") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def _save_unlocked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "experiment": self.experiment,
            "links": [asdict(self.records[key]) for key in sorted(self.records)],
        }
        fd, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
