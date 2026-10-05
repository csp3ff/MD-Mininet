"""Command planning checks for partial time slices; not run in this workspace."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import unittest

from channel_mininet.channel_schedule import schedule_from_dict
from channel_mininet.runtime.channel_shaper import ChannelShaper
from channel_mininet.runtime.names import interface_name
from channel_mininet.schema import load_scene


ROOT = Path(__file__).resolve().parents[1]


class _Process:
    returncode = 0

    def communicate(self, timeout: int):
        return b"", None


class _Node:
    def __init__(self, commands: list[list[str]]):
        self.commands = commands

    def popen(self, args, **_kwargs):
        self.commands.append(list(args))
        return _Process()


class _Network:
    def __init__(self):
        self.commands: list[list[str]] = []

    def get(self, _node_id: str):
        return _Node(self.commands)


class ChannelShaperTests(unittest.TestCase):
    def test_unlisted_links_keep_default_and_later_omission_removes_owned_qdisc(self) -> None:
        scene = load_scene(ROOT / "configs/two_workers.json")
        data = json.loads((ROOT / "configs/channel_profile.reference.json").read_text())
        network = _Network()
        shaper = ChannelShaper(scene, network, ("a",))
        first = schedule_from_dict(data, scene).snapshots[0]
        shaper.apply(first)
        la1_interfaces = {
            interface_name(scene.experiment, "la1", node)
            for node in (scene.links_by_id["la1"].a, scene.links_by_id["la1"].b)
        }
        self.assertEqual({cmd[4] for cmd in network.commands if cmd[:3] == ["tc", "qdisc", "add"]},
                         la1_interfaces)
        self.assertTrue(any("477ns" in cmd for cmd in network.commands))

        later = deepcopy(data)
        later["snapshots"].append({"sim_time_ms": 1000, "links": []})
        second = schedule_from_dict(later, scene).snapshots[1]
        shaper.apply(second)
        deleted = [cmd for cmd in network.commands if cmd[:3] == ["tc", "qdisc", "del"]]
        self.assertEqual({cmd[4] for cmd in deleted}, la1_interfaces)
        self.assertEqual(len(deleted), 2)


if __name__ == "__main__":
    unittest.main()
