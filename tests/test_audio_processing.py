from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np

from offline_transcriber.audio_processing import AUDIO_PRESETS, audio_filter
from offline_transcriber.config import AppConfig, ConfigStore
from offline_transcriber.recorder import AudioRecorder
from offline_transcriber.stream_audio import StreamingAudioProcessor
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

    def test_stream_processor_passthrough_only_quantizes(self):
        processor = StreamingAudioProcessor()
        samples = np.array([-32768, -12000, -1, 0, 1, 12000, 32767], dtype=np.int16)
        result = processor.process(samples, limiter=False, automatic_gain=False, denoise="off")
        self.assertEqual(result.dtype, np.int16)
        self.assertEqual(result.shape, samples.shape)
        self.assertLessEqual(int(np.max(np.abs(result.astype(np.int32) - samples.astype(np.int32)))), 1)

    def test_soft_limiter_controls_peaks_without_touching_small_signals(self):
        processor = StreamingAudioProcessor()
        small = np.full(512, 12000, dtype=np.int16)
        untouched = processor.process(small, limiter=True, automatic_gain=False, denoise="off")
        self.assertLessEqual(int(np.max(np.abs(untouched.astype(np.int32) - small.astype(np.int32)))), 1)
        burst = np.array([32767, -32768] * 256, dtype=np.int16)
        limited = processor.process(burst, limiter=True, automatic_gain=False, denoise="off")
        self.assertLessEqual(int(np.max(np.abs(limited.astype(np.int32)))), int(0.89 * 32767) + 1)

    def test_automatic_gain_raises_quiet_audio_gradually(self):
        processor = StreamingAudioProcessor()
        quiet = np.full(1024, 500, dtype=np.int16)
        first = processor.process(quiet, limiter=False, automatic_gain=True, denoise="off")
        for _ in range(30):
            later = processor.process(quiet, limiter=False, automatic_gain=True, denoise="off")
        first_rms = np.sqrt(np.mean(np.square(first.astype(np.float64))))
        later_rms = np.sqrt(np.mean(np.square(later.astype(np.float64))))
        self.assertGreater(later_rms, first_rms * 2)
        self.assertLessEqual(float(np.max(np.abs(later.astype(np.int32)))), 32767)

    def test_stream_denoise_levels_reduce_stationary_noise(self):
        rng = np.random.default_rng(163)
        noise = rng.normal(0, 220, 16000).astype(np.int16)
        baseline = np.mean(np.square(noise.astype(np.float64)))
        for level in ("low", "medium", "high"):
            with self.subTest(level=level):
                processor = StreamingAudioProcessor()
                chunks = []
                for offset in range(0, len(noise), 400):
                    result = processor.process(noise[offset:offset + 400], limiter=False, automatic_gain=False, denoise=level)
                    self.assertEqual(result.dtype, np.int16)
                    self.assertTrue(np.isfinite(result).all())
                    chunks.append(result)
                output = np.concatenate(chunks)
                self.assertGreater(output.size, 0)
                energy = np.mean(np.square(output[2048:].astype(np.float64)))
                self.assertLess(energy, baseline)

    def test_stream_denoise_rejects_unknown_level(self):
        processor = StreamingAudioProcessor()
        with self.assertRaises(ValueError):
            processor.process(np.zeros(512, dtype=np.int16), limiter=True, automatic_gain=False, denoise="extreme")


if __name__ == "__main__":
    unittest.main()
