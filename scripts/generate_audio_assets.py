"""Generate original, deterministic local WAV assets without external samples."""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
RATE = 44100


def save(name: str, samples: np.ndarray) -> None:
    samples = np.clip(samples, -0.98, 0.98)
    pcm = (samples * 32767).astype("<i2")
    with wave.open(str(ASSETS / name), "wb") as output:
        output.setnchannels(1 if samples.ndim == 1 else samples.shape[1])
        output.setsampwidth(2)
        output.setframerate(RATE)
        output.writeframes(pcm.tobytes())


def filtered_noise(rng: np.random.Generator, count: int, width: int) -> np.ndarray:
    noise = rng.normal(0, 1, count + width)
    return np.convolve(noise, np.hanning(width) / np.hanning(width).sum(), mode="valid")[:count]


def main() -> None:
    ASSETS.mkdir(exist_ok=True)
    rng = np.random.default_rng(20261123)
    seconds = 3.2
    t = np.arange(round(RATE * seconds)) / RATE
    swell = 0.22 + 0.17 * np.sin(2 * np.pi * 0.55 * t - 0.8) ** 2
    surf = filtered_noise(rng, len(t), 13) * 2.5
    body = filtered_noise(rng, len(t), 260) * 5.0
    wave_sound = (surf * 0.40 + body * 0.60) * swell
    fade = np.minimum(1, t / 0.28) * np.minimum(1, (seconds - t) / 0.65)
    wave_sound *= fade
    stereo = np.column_stack((wave_sound, np.roll(wave_sound, 431) * 0.94))
    save("ocean-intro.wav", stereo)

    duration = 0.18
    t = np.arange(round(RATE * duration)) / RATE
    envelope = np.sin(np.pi * t / duration) ** 2
    tone = (np.sin(2 * np.pi * 880 * t) * 0.6 + np.sin(2 * np.pi * 1320 * t) * 0.2) * envelope * 0.22
    save("source-chime.wav", tone)
    print("Generated ocean-intro.wav and source-chime.wav")


if __name__ == "__main__":
    main()
