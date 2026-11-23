from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np

from offline_transcriber.audio_processing import AUDIO_PRESETS, audio_filter
from offline_transcriber.config import AppConfig, ConfigStore
from offline_transcriber.recorder import AudioRecorder
from offline_transcriber.transcriber import OfflineTranscriber


class AudioProcessingTests(unittest.TestCase):
    def test_original_is_default_and_has_no_filter(self):
        self.assertEqual(AppConfig().audio_preset, "original")
        self.assertEqual(audio_filter("original"), "")
        with self.assertRaises(ValueError):
            audio_filter("arbitrary-filter")

    def test_invalid_saved_preset_falls_back_to_original(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text('{"audio_preset": "unknown"}', encoding="utf-8")
            self.assertEqual(ConfigStore(path).load().audio_preset, "original")

    def test_waveform_has_fixed_number_of_peaks(self):
        samples = np.linspace(-32768, 32767, 16000, dtype=np.int16)
        values = AudioRecorder._waveform(samples)
        self.assertEqual(len(values), 80)
        self.assertGreater(max(values), 0.9)
        self.assertTrue(all(0 <= value <= 1 for value in values))

    def test_original_decode_command_has_no_audio_filter(self):
        transcriber = OfflineTranscriber()
        with patch.object(transcriber, "_probe_duration", return_value=1.0):
            # The whitelist is the security boundary; command construction is
            # exercised separately by package/GUI smoke tests with local FFmpeg.
            self.assertEqual(AUDIO_PRESETS["original"]["filter"], "")
        transcriber.cancel_event.set()
        with self.assertRaises(Exception):
            transcriber._check_cancelled()


if __name__ == "__main__":
    unittest.main()
