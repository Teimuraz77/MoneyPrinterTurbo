"""WAV helpers (numpy + stdlib ``wave``; no torch needed)."""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np


def write_wav(path: str | Path, samples: np.ndarray, sr: int) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    x = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((x * 32767).astype("<i2").tobytes())
    return path


def read_wav(path: str | Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        sr, ch, n = w.getframerate(), w.getnchannels(), w.getnframes()
        data = np.frombuffer(w.readframes(n), dtype="<i2").astype(np.float32) / 32767
    if ch > 1:
        data = data.reshape(-1, ch).mean(axis=1)
    return data, sr


def silence(seconds: float, sr: int) -> np.ndarray:
    return np.zeros(int(round(seconds * sr)), dtype=np.float32)


def fake_speech(seconds: float, sr: int, seed: int, pitch: float = 120.0) -> np.ndarray:
    """Speech-like placeholder (voiced harmonics with a ~4 Hz syllable envelope) for dry runs."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * sr)) / sr
    f0 = pitch * (1 + 0.06 * np.sin(2 * np.pi * 0.7 * t + rng.uniform(0, 6)))
    phase = 2 * np.pi * np.cumsum(f0) / sr
    sig = sum((0.5 / k) * np.sin(k * phase) for k in range(1, 6))
    syll = 0.5 * (1 + np.sin(2 * np.pi * rng.uniform(3.5, 4.5) * t + rng.uniform(0, 6)))
    env = np.clip(syll, 0, 1) ** 1.5
    fade = np.minimum(1, np.minimum(t, t[::-1] if len(t) else t) / 0.03)
    return (0.25 * sig * env * fade + 0.003 * rng.standard_normal(len(t))).astype(np.float32)
