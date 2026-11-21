from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from offline_transcriber.config import AppConfig, ConfigStore


class ConfigTests(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            store = ConfigStore(path)
            expected = AppConfig(language="en", beam_size=3, vad_filter=False, output_directory=directory)
            store.save(expected)
            self.assertEqual(store.load(), expected)

    def test_invalid_values_fall_back_safely(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps({"language": "unknown", "beam_size": 999}), encoding="utf-8")
            config = ConfigStore(path).load()
            self.assertEqual(config.language, "zh")
            self.assertEqual(config.beam_size, 10)

    def test_corrupt_file_uses_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text("not-json", encoding="utf-8")
            self.assertEqual(ConfigStore(path).load(), AppConfig())


if __name__ == "__main__":
    unittest.main()
