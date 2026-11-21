from __future__ import annotations

import json
import math
import os
import uuid
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
import onnxruntime as ort

from .paths import VOICEPRINT_LIBRARY_PATH, VOICEPRINT_MODEL_ROOT

MODEL_FILE = "cnceleb_resnet34_LM.onnx"
MODEL_SHA256 = "e7584940aeac8d5512d875e58ce6c09ba4ddad65d8128e1dac0d93aadd087ebb"
UNKNOWN_SPEAKER = "未知说话人"


def normalize(vector: np.ndarray) -> np.ndarray:
    vector = np.asarray(vector, dtype=np.float32).reshape(-1)
    length = float(np.linalg.norm(vector))
    return vector / length if length > 1e-10 else vector


def cosine_similarity(left: np.ndarray, right: np.ndarray) -> float:
    return float(np.dot(normalize(left), normalize(right)))


def kaldi_fbank(audio: np.ndarray, sample_rate: int = 16000, num_mel_bins: int = 80) -> np.ndarray:
    """NumPy Kaldi-compatible fbank: 25 ms Hamming, 10 ms shift, CMN."""
    samples = np.asarray(audio, dtype=np.float32).reshape(-1) * 32768.0
    if samples.size < 400:
        samples = np.pad(samples, (0, 400 - samples.size))
    frame_length = int(sample_rate * 0.025)
    frame_shift = int(sample_rate * 0.010)
    frame_count = 1 + max(0, (samples.size - frame_length) // frame_shift)
    if samples.size < frame_length + (frame_count - 1) * frame_shift:
        samples = np.pad(samples, (0, frame_length + (frame_count - 1) * frame_shift - samples.size))
    indices = np.arange(frame_length)[None, :] + frame_shift * np.arange(frame_count)[:, None]
    frames = samples[indices].copy()
    frames -= frames.mean(axis=1, keepdims=True)
    if frame_count > 1:
        previous = np.concatenate((frames[:, :1], frames[:, :-1]), axis=1)
        frames[:, 1:] -= 0.97 * previous[:, 1:]
        frames[:, 0] -= 0.97 * previous[:, 0]
    else:
        frames[0, 1:] -= 0.97 * frames[0, :-1]
        frames[0, 0] *= 0.03
    frames *= np.hamming(frame_length).astype(np.float32)[None, :]
    spectrum = np.abs(np.fft.rfft(frames, n=512, axis=1)) ** 2

    # Kaldi uses HTK-style triangular Mel filters and includes both FFT endpoints.
    low_mel, high_mel = 20.0, 2595.0 * math.log10(1.0 + sample_rate / 1400.0)
    mel_points = np.linspace(low_mel, high_mel, num_mel_bins + 2)
    hz_points = 700.0 * (10.0 ** (mel_points / 2595.0) - 1.0)
    bins = np.floor((512 + 1) * hz_points / sample_rate).astype(int)
    bins = np.clip(bins, 0, 256)
    filters = np.zeros((num_mel_bins, 257), dtype=np.float32)
    for mel in range(num_mel_bins):
        left, center, right = (int(value) for value in bins[mel:mel + 3])
        for index in range(left, center):
            filters[mel, index] = (index - left) / max(1, center - left)
        for index in range(center, right):
            filters[mel, index] = (right - index) / max(1, right - center)
    energies = spectrum @ filters.T
    features = np.log(np.maximum(energies, np.finfo(np.float32).tiny)).astype(np.float32)
    features -= features.mean(axis=0, keepdims=True)
    return features


class VoiceprintStore:
    def __init__(self, path: Path = VOICEPRINT_LIBRARY_PATH):
        self.path = Path(path)

    def load(self) -> dict[str, list[list[float]]]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            voices = payload.get("voices", {})
            return {
                str(name): [normalize(np.asarray(vector, dtype=np.float32)).tolist() for vector in vectors]
                for name, vectors in voices.items() if vectors
            }
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return {}

    def _save(self, voices: dict[str, list[list[float]]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        temporary.write_text(json.dumps({"version": 1, "voices": voices}, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.path)

    def add(self, name: str, embeddings: Iterable[Sequence[float]]) -> None:
        name = name.strip()
        if not name or name == UNKNOWN_SPEAKER:
            raise ValueError("请输入有效的声纹名称")
        vectors = [normalize(np.asarray(vector, dtype=np.float32)).tolist() for vector in embeddings]
        if not vectors:
            raise ValueError("没有可保存的声纹")
        voices = self.load()
        if name in voices:
            raise ValueError("该声纹名称已存在，可先重命名或删除旧声纹")
        voices[name] = vectors
        self._save(voices)

    def rename(self, old_name: str, new_name: str) -> None:
        voices = self.load()
        new_name = new_name.strip()
        if old_name not in voices:
            raise ValueError("找不到该声纹")
        if not new_name or new_name in voices:
            raise ValueError("新名称为空或已存在")
        voices[new_name] = voices.pop(old_name)
        self._save(voices)

    def delete(self, name: str) -> None:
        voices = self.load()
        voices.pop(name, None)
        self._save(voices)


class SpeakerRecognizer:
    def __init__(self, threshold: float = 0.55, store: VoiceprintStore | None = None):
        self.threshold = max(0.30, min(0.90, float(threshold)))
        self.store = store or VoiceprintStore()
        self._session: ort.InferenceSession | None = None

    def _load(self) -> ort.InferenceSession:
        if self._session is None:
            model = VOICEPRINT_MODEL_ROOT / MODEL_FILE
            if not model.is_file():
                raise FileNotFoundError(f"本地声纹模型缺失：{model}")
            options = ort.SessionOptions()
            options.inter_op_num_threads = 1
            options.intra_op_num_threads = max(1, min(4, os.cpu_count() or 2))
            self._session = ort.InferenceSession(str(model), sess_options=options, providers=["CPUExecutionProvider"])
        return self._session

    def embed(self, audio: np.ndarray) -> np.ndarray:
        if np.asarray(audio).size < 16000 * 0.8:
            raise ValueError("声纹片段至少需要 0.8 秒")
        features = kaldi_fbank(audio)[None, :, :]
        embedding = self._load().run(["embs"], {"feats": features})[0][0]
        return normalize(embedding)

    def annotate(self, audio: np.ndarray, segments: Sequence, known_voices: dict[str, list[list[float]]] | None = None):
        from dataclasses import replace

        voices = known_voices if known_voices is not None else self.store.load()
        centroids: list[np.ndarray] = []
        members: list[list[np.ndarray]] = []
        means: dict[str, list[float]] = {}
        updated = []
        for segment in segments:
            start = max(0, int(segment.start * 16000))
            end = min(len(audio), int(segment.end * 16000))
            if end - start < int(16000 * 0.8):
                updated.append(replace(segment, speaker=UNKNOWN_SPEAKER, speaker_similarity=None))
                continue
            try:
                embedding = self.embed(audio[start:end])
            except ValueError:
                updated.append(replace(segment, speaker=UNKNOWN_SPEAKER, speaker_similarity=None))
                continue
            best_index, best_score = -1, -1.0
            for index, centroid in enumerate(centroids):
                score = cosine_similarity(embedding, centroid)
                if score > best_score:
                    best_index, best_score = index, score
            if best_index < 0 or best_score < self.threshold:
                centroids.append(embedding.copy())
                members.append([embedding])
                best_index, best_score = len(centroids) - 1, 1.0
            else:
                members[best_index].append(embedding)
                centroids[best_index] = normalize(np.mean(members[best_index], axis=0))
            label = f"说话人 {best_index + 1}"
            known_name, known_score = "", -1.0
            for name, vectors in voices.items():
                score = max(cosine_similarity(centroids[best_index], np.asarray(vector)) for vector in vectors)
                if score > known_score:
                    known_name, known_score = name, score
            if known_score >= self.threshold:
                label = known_name
                best_score = known_score
            means[f"说话人 {best_index + 1}"] = centroids[best_index].tolist()
            updated.append(replace(segment, speaker=label, speaker_similarity=round(best_score, 4)))
        return updated, means
