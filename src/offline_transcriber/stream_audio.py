from __future__ import annotations

import numpy as np


DENOISE_LEVELS = {
    "off": (0.0, 1.0),
    "low": (1.2, 0.25),
    "medium": (1.8, 0.16),
    "high": (2.5, 0.08),
}


class StreamingAudioProcessor:
    """Small, dependency-free real-time denoise, gain and soft limiter chain."""

    def __init__(self, frame_size: int = 512):
        self.frame_size = frame_size
        self.hop_size = frame_size // 2
        self.window = np.sqrt(np.hanning(frame_size)).astype(np.float32)
        self.reset()

    def reset(self) -> None:
        self._pending = np.empty(0, dtype=np.float32)
        self._tail = np.zeros(self.hop_size, dtype=np.float32)
        self._noise = None
        self._smooth_gain = None
        self._gain = 1.0
        self._level = None

    def _denoise(self, samples: np.ndarray, level: str) -> np.ndarray:
        if level == "off":
            self._pending = np.empty(0, dtype=np.float32)
            self._tail.fill(0)
            self._noise = None
            self._smooth_gain = None
            return samples
        if level not in DENOISE_LEVELS:
            raise ValueError("未知降噪档位")
        self._pending = np.concatenate((self._pending, samples))
        output = []
        over_subtraction, floor = DENOISE_LEVELS[level]
        while self._pending.size >= self.frame_size:
            block = self._pending[:self.frame_size]
            self._pending = self._pending[self.hop_size:]
            spectrum = np.fft.rfft(block * self.window)
            magnitude = np.abs(spectrum)
            if self._noise is None:
                self._noise = magnitude.copy()
                self._smooth_gain = np.ones_like(magnitude)
            else:
                self._noise = 0.92 * self._noise + 0.08 * np.minimum(self._noise, magnitude)
            gain = np.maximum(floor, 1.0 - over_subtraction * self._noise / (magnitude + 1e-7))
            self._smooth_gain = 0.65 * self._smooth_gain + 0.35 * gain
            filtered = np.fft.irfft(spectrum * self._smooth_gain, n=self.frame_size).astype(np.float32) * self.window
            output.append(filtered[:self.hop_size] + self._tail)
            self._tail = filtered[self.hop_size:].copy()
        return np.concatenate(output).astype(np.float32) if output else np.empty(0, dtype=np.float32)

    def _automatic_gain(self, samples: np.ndarray) -> np.ndarray:
        if samples.size == 0:
            return samples
        rms = float(np.sqrt(np.mean(np.square(samples, dtype=np.float64)) + 1e-12))
        if self._level is None:
            self._level = rms
        else:
            self._level = 0.97 * self._level + 0.03 * rms
        target = min(4.0, max(0.5, 0.1 / max(self._level, 1e-4)))
        smoothing = 0.5 if target < self._gain else 0.025
        self._gain += smoothing * (target - self._gain)
        return samples * self._gain

    @staticmethod
    def _soft_limit(samples: np.ndarray) -> np.ndarray:
        ceiling, knee = 0.89, 0.65
        absolute = np.abs(samples)
        compressed = knee + (ceiling - knee) * np.tanh((absolute - knee) / (ceiling - knee))
        return np.sign(samples) * np.where(absolute <= knee, absolute, compressed)

    def process(self, samples: np.ndarray, *, limiter: bool, automatic_gain: bool, denoise: str) -> np.ndarray:
        values = np.asarray(samples, dtype=np.int16).astype(np.float32) / 32768.0
        if not automatic_gain:
            self._gain = 1.0
            self._level = None
        values = self._denoise(values, denoise)
        if automatic_gain:
            values = self._automatic_gain(values)
        if limiter:
            values = self._soft_limit(values)
        return (np.clip(values, -1.0, 1.0) * 32767.0).astype("<i2")
