"""Parser checks for the controller-owned schedule.  Not run in this workspace."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import unittest

from channel_mininet.channel_schedule import parse_snapshot, schedule_from_dict
from channel_mininet.schema import SceneError, load_scene


ROOT = Path(__file__).resolve().parents[1]


class ChannelScheduleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scene = load_scene(ROOT / "configs/two_workers.json")
        self.reference = json.loads((ROOT / "configs/channel_profile.reference.json").read_text())

    def test_partial_reference_leaves_other_links_at_defaults(self) -> None:
        schedule = schedule_from_dict(self.reference, self.scene)
        self.assertEqual(schedule.snapshots[0].sim_time_ms, 0)
        self.assertEqual([link.link_id for link in schedule.snapshots[0].links], ["la1"])

    def test_full_coverage_and_directional_values(self) -> None:
        data = deepcopy(self.reference)
        template = data["snapshots"][0]["links"][0]
        template["a_to_b"]["netem_delay_ms"] = 0.001
        template["b_to_a"]["netem_delay_ms"] = 0.001
        data["snapshots"][0]["links"] = [
            {**deepcopy(template), "link_id": link.id} for link in self.scene.links
        ]
        data["snapshots"].append(deepcopy(data["snapshots"][0]))
        data["snapshots"][1]["sim_time_ms"] = 1000
        data["snapshots"][1]["links"][0]["b_to_a"]["bandwidth_mbps"] = 50
        schedule = schedule_from_dict(data, self.scene)
        self.assertEqual(len(schedule.snapshots), 2)
        self.assertNotEqual(schedule.snapshots[0].digest, schedule.snapshots[1].digest)

    def test_rejects_duplicate_or_unordered_snapshots(self) -> None:
        data = deepcopy(self.reference)
        data["snapshots"].append(deepcopy(data["snapshots"][0]))
        with self.assertRaisesRegex(SceneError, "strictly increasing"):
            schedule_from_dict(data, self.scene)

    def test_rejects_delay_below_one_nanosecond(self) -> None:
        data = deepcopy(self.reference)
        data["snapshots"][0]["links"][0]["a_to_b"]["netem_delay_ms"] = 0.0000001
        with self.assertRaisesRegex(SceneError, "rounds to zero nanoseconds"):
            schedule_from_dict(data, self.scene)

    def test_rejects_missing_direction(self) -> None:
        data = deepcopy(self.reference)
        del data["snapshots"][0]["links"][0]["b_to_a"]
        with self.assertRaisesRegex(SceneError, "b_to_a must be an object"):
            schedule_from_dict(data, self.scene)

    def test_wire_digest_detects_changed_values(self) -> None:
        snapshot = schedule_from_dict(self.reference, self.scene).snapshots[0]
        wire = snapshot.to_dict()
        wire["links"][0]["a_to_b"]["bandwidth_mbps"] = 100
        with self.assertRaisesRegex(SceneError, "digest does not match"):
            parse_snapshot(wire, self.scene, 0)


if __name__ == "__main__":
    unittest.main()
