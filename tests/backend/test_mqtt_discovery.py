from __future__ import annotations

import unittest

from signalbar.mqtt.discovery import BASE_EVENT_TYPES, Topics, discovery_messages, node_id_for


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.topics = Topics("gabecubeaura", node_id_for("SteamMachine.local"), "homeassistant")
        self.messages = discovery_messages(self.topics, "1.4.0", "steammachine", BASE_EVENT_TYPES)

    def by_suffix(self, suffix):
        return next(p for _, p in self.messages if p["unique_id"].endswith(suffix))

    def test_every_entity_is_unique_named_and_tied_to_the_device(self):
        unique_ids = set()
        for topic, payload in self.messages:
            self.assertEqual(topic, f"homeassistant/{topic.split('/')[1]}/{payload['unique_id']}/config")
            self.assertIn(topic.split("/")[1], ("sensor", "binary_sensor", "event", "image"))
            self.assertEqual(payload["device"]["identifiers"], ["gabecubeaura_steammachine_local"])
            self.assertIn({"topic": self.topics.availability}, payload["availability"])
            self.assertIs(payload["has_entity_name"], True)
            self.assertNotIn("GabeCubeAura", payload["name"])
            unique_ids.add(payload["unique_id"])
        self.assertEqual(len(unique_ids), len(self.messages))
        self.assertIn({"topic": self.topics.frontend}, self.by_suffix("_current_game")["availability"])
        self.assertNotIn({"topic": self.topics.frontend}, self.by_suffix("_thermal_protection")["availability"])
        # Hundreds of status keys as attributes would be recorded again on every change.
        self.assertNotIn(self.topics.state("status"), {p.get("json_attributes_topic") for _, p in self.messages})


if __name__ == "__main__":
    unittest.main()
