from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from PySide6.QtWidgets import QApplication

from offline_transcriber.audio_library import AudioLibrary
from offline_transcriber.meeting import clean_markers, clock_time, marker_text, normalize_hotwords, polish_transcript
from offline_transcriber.review_panel import TranscriptReviewPanel
from offline_transcriber.transcriber import SegmentData, TranscriptionResult, result_from_dict


class MeetingToolsTests(unittest.TestCase):
    def test_hotwords_are_normalized_and_limited(self):
        value = normalize_hotwords(" 观海听涛，麒麟、观海听涛；量子通信\n" + "，".join(f"词{i}" for i in range(40)))
        words = value.split("，")
        self.assertEqual(len(words), 30)
        self.assertEqual(words[:3], ["观海听涛", "麒麟", "量子通信"])
        self.assertEqual(normalize_hotwords("，、；"), "")

    def test_markers_are_validated_sorted_and_formatted(self):
        markers = clean_markers([
            {"seconds": 62.8, "type": "待办", "note": "  整理   纪要  "},
            {"seconds": 3, "type": "重点", "note": ""},
        ])
        self.assertEqual(markers[0]["note"], "")
        self.assertEqual(marker_text(markers[1]), "00:01:02  【待办】 · 整理 纪要")
        self.assertEqual(clock_time(3661), "01:01:01")
        with self.assertRaises(ValueError):
            clean_markers([{"seconds": -1, "type": "重点"}])
        with self.assertRaises(ValueError):
            clean_markers([{"seconds": 0, "type": "其他"}])

    def test_conservative_cleanup_keeps_source_labels_and_content(self):
        text = "【会议】\n嗯，确定下周提交方案！！\n这是  观海 听涛  的测试。\n"
        cleaned = polish_transcript(text)
        self.assertIn("【会议】", cleaned)
        self.assertIn("确定下周提交方案！", cleaned)
        self.assertIn("观海听涛", cleaned)

    def test_meeting_notes_share_audio_vault_encryption(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "meeting.wav"
            audio.write_bytes(b"RIFF test")
            library = AudioLibrary(root / "vault")
            item = library.add(audio, "评审会")
            library.set_meeting(item["id"], "季度评审", [{"seconds": 8, "type": "决定", "note": "采用离线方案"}])
            library.enable_encryption("a secure password")
            self.assertNotIn("季度评审".encode(), library.encrypted_index_path.read_bytes())
            library.lock()
            library.unlock("a secure password")
            self.assertEqual(library.items()[0]["meeting_topic"], "季度评审")
            self.assertIn("00:00:08", library.meeting_markdown(item["id"]))


class ReviewPanelTests(unittest.TestCase):
    def test_minutes_include_source_time_markers(self):
        from offline_transcriber.minutes import generate_minutes
        result = TranscriptionResult(
            source="meeting.wav", model="local", language="zh", language_probability=1,
            duration=70, created_at="now", sources=("meeting.wav",),
            segments=(SegmentData(0, 4, "确定下周提交离线部署方案。"),),
        )
        content = generate_minutes(result, meeting_notes=[{
            "source": "项目评审", "markers": [{"seconds": 3, "type": "决定", "note": "先验收短音频"}],
        }])
        self.assertIn("会中打点", content)
        self.assertIn("00:00:03", content)
        self.assertIn("先验收短音频", content)

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.result = TranscriptionResult(
            source="meeting.wav", model="local", language="zh", language_probability=1,
            duration=70, created_at="now", sources=("meeting.wav",),
            segments=(SegmentData(0, 4, "第一句", speaker="甲"), SegmentData(61, 65, "第二句", speaker="乙")),
        )
        self.panel = TranscriptReviewPanel()
        self.panel.set_result(self.result)

    def tearDown(self):
        self.panel.shutdown()
        self.panel.close()

    def test_saved_result_and_local_edit_roundtrip(self):
        restored = result_from_dict(json.loads(json.dumps(self.result.to_dict())))
        self.assertEqual(restored.segments[1].start, 61)
        item = self.panel.table.item(1, 2)
        item.setText("第二句已校订")
        self.assertEqual(self.panel.result.segments[1].text, "第二句已校订")
        self.assertEqual(self.panel.result.segments[0].text, "第一句")

    def test_full_text_and_speaker_filters(self):
        self.panel.search.setText("第二")
        self.assertTrue(self.panel.table.isRowHidden(0))
        self.assertFalse(self.panel.table.isRowHidden(1))
        self.panel.search.clear()
        self.panel.speaker_filter.setCurrentIndex(self.panel.speaker_filter.findData("甲"))
        self.assertFalse(self.panel.table.isRowHidden(0))
        self.assertTrue(self.panel.table.isRowHidden(1))


if __name__ == "__main__":
    unittest.main()
