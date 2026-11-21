from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from offline_transcriber.document_export import save_document
from offline_transcriber.minutes import generate_minutes
from offline_transcriber.record_naming import read_record_text, rename_record, suggest_name_from_text
from offline_transcriber.speaker import SpeakerRecognizer, VoiceprintStore, cosine_similarity, normalize
from offline_transcriber.transcriber import SegmentData, TranscriptionResult
from offline_transcriber.update_common import safe_relative_path


class SpeakerTests(unittest.TestCase):
    def test_store_persists_and_renames(self):
        with tempfile.TemporaryDirectory() as directory:
            store = VoiceprintStore(Path(directory) / "voiceprints.json")
            store.add("张三", [np.ones(256)])
            self.assertIn("张三", store.load())
            store.rename("张三", "李四")
            self.assertNotIn("张三", store.load())
            self.assertEqual(len(store.load()["李四"]), 1)
            store.delete("李四")
            self.assertEqual(store.load(), {})

    def test_short_segments_are_unknown_and_named_voice_matches(self):
        recognizer = SpeakerRecognizer(threshold=0.55)
        recognizer.embed = lambda audio: np.ones(256, dtype=np.float32)  # deterministic model-independent clustering test
        segments = [
            SegmentData(0, 0.2, "太短"),
            SegmentData(0.2, 1.4, "第一句"),
            SegmentData(1.4, 2.6, "第二句"),
        ]
        updated, means = recognizer.annotate(np.zeros(41600, dtype=np.float32), segments, {"张三": [np.ones(256).tolist()]})
        self.assertEqual(updated[0].speaker, "未知说话人")
        self.assertEqual(updated[1].speaker, "张三")
        self.assertEqual(updated[2].speaker, "张三")
        self.assertIn("说话人 1", means)

    def test_cosine_normalization(self):
        self.assertAlmostEqual(cosine_similarity(np.array([2, 0]), np.array([3, 0])), 1.0)
        self.assertEqual(float(np.linalg.norm(normalize(np.array([3, 4])))), 1.0)

    def test_voiceprint_update_cannot_replace_asr_or_user_data(self):
        voiceprint = "models/wespeaker-cnceleb-resnet34-LM/cnceleb_resnet34_LM.onnx"
        self.assertEqual(safe_relative_path(voiceprint, allow_voiceprint_model=True), voiceprint)
        with self.assertRaises(ValueError):
            safe_relative_path("models/faster-whisper-medium/model.bin", allow_voiceprint_model=True)
        with self.assertRaises(ValueError):
            safe_relative_path("data/voiceprints.json", allow_voiceprint_model=True)
        with self.assertRaises(ValueError):
            safe_relative_path(voiceprint)


class RecordNamingTests(unittest.TestCase):
    def test_explicit_title_and_fallback(self):
        self.assertEqual(suggest_name_from_text("讨论\n标题：山海项目周会\n正文"), "山海项目周会")
        self.assertEqual(suggest_name_from_text("【说话人 1】确定下周提交方案。"), "确定下周提交方案")
        self.assertEqual(suggest_name_from_text("文件名：A/B:C*D?\n"), "A B C D")
        self.assertEqual(suggest_name_from_text("标题：CON"), "记录_CON")
        self.assertEqual(suggest_name_from_text("00:00:01,000 --> 00:00:03,000"), "")

    def test_rename_record_and_collision(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "批量_1"
            source.mkdir()
            for suffix in (".txt", ".srt", ".vtt", ".json"):
                (source / f"批量_1{suffix}").write_text("标题：测试", encoding="utf-8")
            (source / "batch-report.json").write_text("{}", encoding="utf-8")
            destination = rename_record(source, "山海会议")
            self.assertEqual(destination.name, "山海会议")
            self.assertTrue((destination / "山海会议.docx").exists() is False)
            self.assertTrue((destination / "山海会议.txt").is_file())
            self.assertTrue((destination / "batch-report.json").is_file())
            self.assertEqual(read_record_text(destination), "标题：测试")
            other = root / "other"
            other.mkdir()
            with self.assertRaises(FileExistsError):
                rename_record(other, "山海会议")


class MinutesAndExportTests(unittest.TestCase):
    def result(self):
        return TranscriptionResult(
            source="meeting.wav", model="small", language="zh", language_probability=1.0,
            duration=120, created_at="now", sources=("meeting.wav",),
            segments=(
                SegmentData(0, 3, "标题：山海项目周会", speaker="张三"),
                SegmentData(3, 8, "会议确定采用离线部署方案。", speaker="张三"),
                SegmentData(8, 15, "李四负责下周提交测试报告。", speaker="李四"),
            ),
        )

    def test_minutes(self):
        content = generate_minutes(self.result())
        self.assertIn("山海项目周会纪要", content)
        self.assertIn("张三、李四", content)
        self.assertIn("决定事项", content)
        self.assertIn("李四负责下周提交测试报告", content)
        self.assertIn("未使用在线服务或生成式大模型", content)

    def test_txt_md_docx_exports(self):
        with tempfile.TemporaryDirectory() as directory:
            for suffix in (".txt", ".md", ".docx"):
                path = save_document(Path(directory) / f"纪要{suffix}", "# 测试纪要\n\n- 待办事项", "测试纪要")
                self.assertTrue(path.is_file())
                self.assertGreater(path.stat().st_size, 20)
            from docx import Document
            text = "\n".join(paragraph.text for paragraph in Document(Path(directory) / "纪要.docx").paragraphs)
            self.assertIn("测试纪要", text)
            self.assertIn("待办事项", text)


if __name__ == "__main__":
    unittest.main()
