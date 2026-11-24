from __future__ import annotations

import unittest
import wave
from pathlib import Path

from PySide6.QtGui import QImage

from offline_transcriber.paths import APP_ROOT
from offline_transcriber.tutorial_content import TUTORIAL_CHAPTERS
from offline_transcriber.tutorial_panel import TutorialPanel


class TutorialTests(unittest.TestCase):
    def test_twelve_detailed_chapters_and_unique_assets(self):
        self.assertEqual(len(TUTORIAL_CHAPTERS), 12)
        self.assertEqual([item["number"] for item in TUTORIAL_CHAPTERS], list(range(1, 13)))
        self.assertEqual(len({item["audio"] for item in TUTORIAL_CHAPTERS}), 12)
        for item in TUTORIAL_CHAPTERS:
            with self.subTest(chapter=item["number"]):
                self.assertGreater(len(item["body"]), 300)
                self.assertGreater(len(item["narration"]), 100)
                self.assertIn(item["title"], TutorialPanel._html(item))

    def test_all_local_narration_files_are_valid_wav(self):
        durations = []
        for item in TUTORIAL_CHAPTERS:
            path = APP_ROOT / item["audio"]
            self.assertTrue(path.is_file(), path)
            with wave.open(str(path), "rb") as audio:
                self.assertEqual(audio.getnchannels(), 1)
                self.assertGreater(audio.getframerate(), 8000)
                duration = audio.getnframes() / audio.getframerate()
                self.assertGreater(duration, 5)
                durations.append(duration)
        self.assertGreater(sum(durations), 300)

    def test_every_chapter_has_diagram_and_real_screenshot(self):
        for item in TUTORIAL_CHAPTERS:
            with self.subTest(chapter=item["number"]):
                self.assertEqual(len(item["steps"]), 4)
                for key in ("diagram", "screenshot"):
                    path = APP_ROOT / item[key]
                    self.assertTrue(path.is_file(), path)
                    image = QImage(str(path))
                    self.assertFalse(image.isNull(), path)
                    self.assertEqual(image.width(), 1200)
                html = TutorialPanel._html(item)
                self.assertEqual(html.count("<img "), 2)
                self.assertIn(item["caption"], html)

    def test_player_time_format(self):
        self.assertEqual(TutorialPanel._time(0), "00:00")
        self.assertEqual(TutorialPanel._time(65_999), "01:05")


if __name__ == "__main__":
    unittest.main()
