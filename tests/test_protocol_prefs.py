import tempfile
import unittest
from pathlib import Path

from linkray.protocol_prefs import (
    ADVANCED_PROTOCOL_KEYS,
    ProtocolPreferences,
    enabled_protocols_for_user,
    load_protocol_preferences,
    save_protocol_preferences,
)


class ProtocolPreferenceTests(unittest.TestCase):
    def test_missing_user_defaults_to_all_advanced_protocols(self):
        prefs = ProtocolPreferences(users={})

        self.assertEqual(enabled_protocols_for_user(prefs, "cyclelink"), set(ADVANCED_PROTOCOL_KEYS))

    def test_save_and_load_user_protocol_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "users.json"
            prefs = ProtocolPreferences(users={"lichen": {"snell", "hysteria2"}})

            save_protocol_preferences(path, prefs)
            loaded = load_protocol_preferences(path)

        self.assertEqual(enabled_protocols_for_user(loaded, "lichen"), {"snell", "hysteria2"})

    def test_unknown_protocol_keys_are_ignored(self):
        prefs = ProtocolPreferences(users={"lichen": {"snell", "bad-key"}})

        self.assertEqual(enabled_protocols_for_user(prefs, "lichen"), {"snell"})


if __name__ == "__main__":
    unittest.main()
