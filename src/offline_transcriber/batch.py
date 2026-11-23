from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from .transcriber import OfflineTranscriber, SegmentData, TranscriptionCancelled, TranscriptionResult


QUEUE_MODE = "queue"
MERGED_MODE = "merged"


@dataclass(frozen=True)
class BatchFailure:
    source: str
    error: str

    def to_dict(self) -> dict:
        return {"source": self.source, "error": self.error}


@dataclass(frozen=True)
class BatchSummary:
    mode: str
    results: tuple[TranscriptionResult, ...]
    failures: tuple[BatchFailure, ...]
    merged_result: TranscriptionResult

    @property
    def succeeded_count(self) -> int:
        return len(self.results)

    @property
    def failed_count(self) -> int:
        return len(self.failures)


def merge_results(results: Iterable[TranscriptionResult], mode: str = MERGED_MODE) -> TranscriptionResult:
    ordered = tuple(results)
    if not ordered:
        raise ValueError("没有可合并的转录结果")
    segments: list[SegmentData] = []
    speaker_embeddings: dict[str, list[float]] = {}
    offset = 0.0
    for source_index, result in enumerate(ordered):
        for segment in result.segments:
            segments.append(SegmentData(
                start=segment.start + offset,
                end=segment.end + offset,
                text=segment.text,
                source=result.source,
                source_index=source_index,
                speaker=segment.speaker,
                speaker_similarity=segment.speaker_similarity,
            ))
        for label, vector in (result.speaker_embeddings or {}).items():
            speaker_embeddings[f"{source_index}:{label}"] = vector
        offset += max(0.0, result.duration)
    first = ordered[0]
    languages = {result.language for result in ordered}
    return TranscriptionResult(
        source=first.source if len(ordered) == 1 else f"{len(ordered)} 个文件",
        model=first.model,
        language=first.language if len(languages) == 1 else "mixed",
        language_probability=first.language_probability if len(ordered) == 1 else None,
        duration=offset,
        segments=tuple(segments),
        created_at=datetime.now(timezone.utc).astimezone().isoformat(),
        sources=tuple(result.source for result in ordered),
        batch_mode=mode,
        speaker_embeddings=speaker_embeddings or None,
    )


def transcribe_batch(
    transcriber: OfflineTranscriber,
    sources: Iterable[str | Path],
    mode: str = QUEUE_MODE,
    language: str = "zh",
    beam_size: int = 5,
    vad_filter: bool = True,
    audio_preset: str = "original",
    progress: Callable[[int, str], None] | None = None,
    on_segment: Callable[[SegmentData], None] | None = None,
    log: Callable[[str], None] | None = None,
    file_started: Callable[[str, int, int], None] | None = None,
    file_completed: Callable[[TranscriptionResult, int, int], None] | None = None,
    file_failed: Callable[[str, str, int, int], None] | None = None,
) -> BatchSummary:
    ordered_sources = [str(Path(source).resolve()) for source in sources]
    if not ordered_sources:
        raise ValueError("请至少选择一个音频或视频文件")
    if mode not in {QUEUE_MODE, MERGED_MODE}:
        raise ValueError(f"未知批量执行模式：{mode}")
    progress = progress or (lambda _value, _message: None)
    on_segment = on_segment or (lambda _segment: None)
    log = log or (lambda _message: None)
    file_started = file_started or (lambda _source, _index, _total: None)
    file_completed = file_completed or (lambda _result, _index, _total: None)
    file_failed = file_failed or (lambda _source, _error, _index, _total: None)

    total = len(ordered_sources)
    results: list[TranscriptionResult] = []
    failures: list[BatchFailure] = []
    completed_duration = 0.0
    for index, source in enumerate(ordered_sources):
        transcriber._check_cancelled()
        name = Path(source).name
        file_started(source, index, total)
        log(f"开始第 {index + 1}/{total} 个文件：{name}")

        def file_progress(value: int, message: str, current=index) -> None:
            overall = min(99, int((current + max(0, min(100, value)) / 100) / total * 100))
            progress(overall, f"[{current + 1}/{total}] {name} · {message}")

        def file_segment(segment: SegmentData, current=index, base=completed_duration) -> None:
            on_segment(SegmentData(
                start=segment.start + (base if mode == MERGED_MODE else 0.0),
                end=segment.end + (base if mode == MERGED_MODE else 0.0),
                text=segment.text,
                source=source,
                source_index=current,
                speaker=segment.speaker,
                speaker_similarity=segment.speaker_similarity,
            ))

        try:
            result = transcriber.transcribe(
                source,
                language=language,
                beam_size=beam_size,
                vad_filter=vad_filter,
                audio_preset=audio_preset,
                progress=file_progress,
                on_segment=file_segment,
                log=log,
            )
        except TranscriptionCancelled:
            raise
        except Exception as exc:
            failure = BatchFailure(source, str(exc))
            failures.append(failure)
            file_failed(source, str(exc), index, total)
            log(f"第 {index + 1}/{total} 个文件失败，继续后续队列：{exc}")
            continue
        results.append(result)
        completed_duration += result.duration
        file_completed(result, index, total)
        progress(int((index + 1) / total * 100), f"已完成 {index + 1}/{total} 个文件")

    if not results:
        details = "；".join(f"{Path(item.source).name}: {item.error}" for item in failures)
        raise RuntimeError("全部文件转录失败。" + details)
    merged = merge_results(results, mode=mode)
    progress(100, f"批量完成：成功 {len(results)} 个，失败 {len(failures)} 个")
    return BatchSummary(mode, tuple(results), tuple(failures), merged)
