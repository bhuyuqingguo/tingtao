from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from offline_transcriber.batch import MERGED_MODE, QUEUE_MODE, merge_results, transcribe_batch
from offline_transcriber.formatters import result_text, to_srt
from offline_transcriber.transcriber import SegmentData, TranscriptionResult


def make_result(source: str, text: str, duration: float = 10.0) -> TranscriptionResult:
    return TranscriptionResult(
        source=source,
        model="fake-small",
        language="zh",
        language_probability=1.0,
        duration=duration,
        segments=(SegmentData(0.0, 1.0, text),),
        created_at="2026-11-19T00:00:00+08:00",
        sources=(source,),
    )


class FakeTranscriber:
    def __init__(self):
        self.calls = []

    def _check_cancelled(self):
        return None

    def transcribe(self, source, **kwargs):
        source = str(Path(source).resolve())
        self.calls.append(source)
        if "bad" in source:
            raise RuntimeError("模拟坏文件")
        result = make_result(source, f"文稿:{Path(source).name}", 10.0)
        kwargs["on_segment"](SegmentData(0.0, 1.0, result.segments[0].text))
        kwargs["progress"](100, "完成")
        return result


class BatchTests(unittest.TestCase):
    def test_merge_offsets_timestamps_and_marks_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            first = str(Path(directory) / "a.wav")
            second = str(Path(directory) / "b.wav")
            merged = merge_results((make_result(first, "第一段"), make_result(second, "第二段")))
            self.assertEqual(merged.duration, 20.0)
            self.assertEqual(merged.segments[1].start, 10.0)
            self.assertEqual(merged.segments[1].end, 11.0)
            self.assertEqual(merged.segments[1].source, second)
            self.assertIn("【a.wav】", result_text(merged))
            self.assertIn("【b.wav】", result_text(merged))
            self.assertIn("00:00:10,000 --> 00:00:11,000", to_srt(merged))
            self.assertEqual(merged.batch_mode, MERGED_MODE)

    def test_queue_runs_in_order_and_continues_after_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            sources = [str(Path(directory) / name) for name in ("a.wav", "bad.wav", "b.wav")]
            fake = FakeTranscriber()
            started = []
            failed = []
            summary = transcribe_batch(
                fake,
                sources,
                mode=QUEUE_MODE,
                file_started=lambda source, index, total: started.append((index, total)),
                file_failed=lambda source, error, index, total: failed.append((index, error)),
            )
            self.assertEqual(fake.calls, [str(Path(source).resolve()) for source in sources])
            self.assertEqual(started, [(0, 3), (1, 3), (2, 3)])
            self.assertEqual(summary.succeeded_count, 2)
            self.assertEqual(summary.failed_count, 1)
            self.assertEqual(failed[0][0], 1)
            self.assertEqual(summary.merged_result.duration, 20.0)
            self.assertEqual(summary.merged_result.batch_mode, QUEUE_MODE)

    def test_merged_live_segments_use_global_timeline(self):
        with tempfile.TemporaryDirectory() as directory:
            sources = [str(Path(directory) / name) for name in ("a.wav", "b.wav")]
            live = []
            summary = transcribe_batch(FakeTranscriber(), sources, mode=MERGED_MODE, on_segment=live.append)
            self.assertEqual([segment.start for segment in live], [0.0, 10.0])
            self.assertEqual([segment.source_index for segment in live], [0, 1])
            self.assertEqual(summary.failed_count, 0)

    def test_all_failures_raise_a_clear_error(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "全部文件转录失败"):
                transcribe_batch(FakeTranscriber(), [str(Path(directory) / "bad.wav")])

    def test_empty_batch_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "至少选择"):
            transcribe_batch(FakeTranscriber(), [])


if __name__ == "__main__":
    unittest.main()
