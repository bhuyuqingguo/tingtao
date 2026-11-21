from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from offline_transcriber.formatters import export_all, format_timestamp, to_json, to_srt, to_vtt


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Result:
    segments: tuple[Segment, ...]

    def to_dict(self):
        return {"segments": [segment.__dict__ for segment in self.segments]}


class FormatterTests(unittest.TestCase):
    def setUp(self):
        self.result = Result((Segment(0.0, 1.25, "你好。"), Segment(61.5, 62.0, "测试。")))

    def test_timestamps(self):
        self.assertEqual(format_timestamp(61.5), "00:01:01,500")
        self.assertEqual(format_timestamp(61.5, vtt=True), "00:01:01.500")
        self.assertEqual(format_timestamp(3661.001), "01:01:01,001")

    def test_srt_and_vtt(self):
        srt = to_srt(self.result)
        self.assertIn("1\n00:00:00,000 --> 00:00:01,250\n你好。", srt)
        self.assertTrue(to_vtt(self.result).startswith("WEBVTT\n"))

    def test_json_preserves_chinese_and_edits(self):
        payload = json.loads(to_json(self.result, "编辑后的文稿"))
        self.assertEqual(payload["text"], "编辑后的文稿")
        self.assertEqual(payload["segments"][0]["text"], "你好。")

    def test_export_all(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = export_all(self.result, Path(directory), "sample")
            self.assertEqual({path.suffix for path in paths}, {".txt", ".srt", ".vtt", ".json"})
            for path in paths:
                self.assertTrue(path.is_file())
                self.assertGreater(path.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
