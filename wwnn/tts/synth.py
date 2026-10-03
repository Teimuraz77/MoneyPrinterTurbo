"""TTS stage: Chatterbox (English, zero-shot voice cloning from reference WAVs).

Runs in the ``tts`` container (``python -m wwnn.tts.synth --run-dir ...``) or in-process.
Synthesises sentence by sentence (short inputs limit drift), caches each sentence WAV by
content hash (resume), joins with fixed pauses, resamples to 48 kHz, high-passes and
loudness-normalises each anchor track. Exact sentence timings are recorded so subtitles
need no speech recognition.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np
from loguru import logger

from wwnn.config import Settings
from wwnn.script.text import count_words, normalize_for_tts, split_sentences
from wwnn.tts.audio import fake_speech, read_wav, silence, write_wav
from wwnn.util import StageError, ffmpeg, read_json, sha256_json, write_json


def build_job(doc: dict, settings: Settings) -> dict:
    """Turn an approved script document into a TTS job (sentences already normalised)."""
    segs = []
    for i, s in enumerate(doc["segments"]):
        sentences = [{"text": t, "tts_text": normalize_for_tts(t)} for t in split_sentences(s["text"])]
        segs.append({"idx": i, "anchor": s["anchor"], "kind": s["kind"], "item_slot": s.get("item_slot"),
                     "sentences": sentences})
    voices = {
        "tom": {"ref": str(settings.path(settings.tom_voice_ref)), "exaggeration": settings.tom_exaggeration,
                "cfg_weight": settings.tom_cfg_weight, "seed": settings.tts_seed_tom},
        "annika": {"ref": str(settings.path(settings.annika_voice_ref)), "exaggeration": settings.annika_exaggeration,
                   "cfg_weight": settings.annika_cfg_weight, "seed": settings.tts_seed_annika},
    }
    return {"segments": segs, "voices": voices, "model": settings.chatterbox_model,
            "temperature": settings.tts_temperature, "sentence_pause_s": settings.tts_sentence_pause_s,
            "segment_pause_s": settings.tts_segment_pause_s, "sample_rate": settings.tts_sample_rate}


class ChatterboxEngine:
    def __init__(self, model_name: str, device: str):
        import torch  # noqa: F401  (only inside the tts container)

        if model_name == "turbo":
            from chatterbox.tts_turbo import ChatterboxTurboTTS
            self.model = ChatterboxTurboTTS.from_pretrained(device=device)
        else:
            from chatterbox.tts import ChatterboxTTS
            self.model = ChatterboxTTS.from_pretrained(device=device)
        self.sr = self.model.sr
        self.model_name = model_name
        self._prepared: str | None = None

    def synth(self, text: str, voice: dict, temperature: float) -> np.ndarray:
        import torch

        key = f"{voice['ref']}|{voice['exaggeration']}"
        if self._prepared != key:
            if not Path(voice["ref"]).is_file():
                raise StageError(f"voice reference WAV missing: {voice['ref']}")
            self.model.prepare_conditionals(voice["ref"], exaggeration=voice["exaggeration"])
            self._prepared = key
        torch.manual_seed(voice["seed"])
        kwargs = {"temperature": temperature}
        if self.model_name != "turbo":
            kwargs.update(exaggeration=voice["exaggeration"], cfg_weight=voice["cfg_weight"])
        wav = self.model.generate(text, **kwargs)
        return wav.squeeze(0).detach().cpu().numpy().astype(np.float32)


class MockEngine:
    """Dry-run engine: speech-like tones, duration from word count at the configured wpm."""

    def __init__(self, wpm: dict[str, float], sr: int = 24000):
        self.sr = sr
        self.wpm = wpm

    def synth(self, text: str, voice: dict, temperature: float) -> np.ndarray:
        anchor = voice.get("anchor", "tom")
        secs = max(0.6, count_words(text) / self.wpm.get(anchor, 150) * 60)
        return fake_speech(secs, self.sr, seed=voice["seed"] + len(text),
                           pitch=115.0 if anchor == "tom" else 205.0)


def run_tts(run_dir: Path, engine, job: dict | None = None) -> dict:
    tts_dir = run_dir / "tts"
    job = job or read_json(tts_dir / "job.json")
    cache = tts_dir / "sentences"
    cache.mkdir(parents=True, exist_ok=True)
    sr = engine.sr
    tracks: dict[str, dict] = {}
    t0 = time.time()
    for anchor in ("tom", "annika"):
        voice = dict(job["voices"][anchor], anchor=anchor)
        pieces: list[np.ndarray] = []
        cursor = 0.0
        segs_out = []
        anchor_segs = [s for s in job["segments"] if s["anchor"] == anchor]
        for si, seg in enumerate(anchor_segs):
            if si:
                pieces.append(silence(job["segment_pause_s"], sr))
                cursor += job["segment_pause_s"]
            seg_start = cursor
            sents_out = []
            for k, sent in enumerate(seg["sentences"]):
                if k:
                    pieces.append(silence(job["sentence_pause_s"], sr))
                    cursor += job["sentence_pause_s"]
                key = sha256_json([sent["tts_text"], voice, job["model"], job["temperature"],
                                   type(engine).__name__])[:20]
                f = cache / f"{anchor}_{key}.wav"
                if f.exists():
                    wav, _ = read_wav(f)
                else:
                    wav = engine.synth(sent["tts_text"], voice, job["temperature"])
                    wav = _trim_silence(wav, sr)
                    write_wav(f, wav, sr)
                pieces.append(wav)
                dur = len(wav) / sr
                sents_out.append({"text": sent["text"], "start": round(cursor, 3), "end": round(cursor + dur, 3)})
                cursor += dur
            segs_out.append({"idx": seg["idx"], "kind": seg["kind"], "item_slot": seg.get("item_slot"),
                             "start": round(seg_start, 3), "end": round(cursor, 3), "sentences": sents_out})
        raw = tts_dir / f"{anchor}_raw.wav"
        write_wav(raw, np.concatenate(pieces) if pieces else silence(0.5, sr), sr)
        out = tts_dir / f"{anchor}.wav"
        # 48 kHz, gentle high-pass, per-anchor loudness normalisation (final master is -14 LUFS)
        ffmpeg(["-i", raw, "-af", f"highpass=f=80,loudnorm=I=-16:TP=-1.5:LRA=11,aresample={job['sample_rate']}",
                "-ar", str(job["sample_rate"]), "-ac", "1", out])
        raw.unlink(missing_ok=True)
        words = sum(count_words(s["text"]) for seg in anchor_segs for s in seg["sentences"])
        speech = sum(s["end"] - s["start"] for seg in segs_out for s in seg["sentences"])
        tracks[anchor] = {"wav": out.name, "duration": round(cursor, 3), "segments": segs_out,
                          "words": words, "speech_seconds": round(speech, 3),
                          "wpm": round(words / speech * 60, 1) if speech else None}
        logger.info(f"tts {anchor}: {cursor:.1f}s, {words} words")
    manifest = {"tracks": tracks, "engine": type(engine).__name__, "seconds": round(time.time() - t0, 1)}
    write_json(tts_dir / "manifest.json", manifest)
    return manifest


def _trim_silence(wav: np.ndarray, sr: int, thresh: float = 0.01, pad: float = 0.05) -> np.ndarray:
    idx = np.where(np.abs(wav) > thresh)[0]
    if not len(idx):
        return wav
    a, b = max(0, idx[0] - int(pad * sr)), min(len(wav), idx[-1] + int(pad * sr))
    return wav[a:b]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="WWNN TTS stage (Chatterbox)")
    ap.add_argument("--run-dir", required=True, type=Path)
    ap.add_argument("--mock", action="store_true")
    args = ap.parse_args(argv)
    settings = Settings.from_env()
    if args.mock or settings.dry_run:
        engine = MockEngine({"tom": settings.wpm_tom, "annika": settings.wpm_annika})
    else:
        engine = ChatterboxEngine(settings.chatterbox_model, settings.tts_device)
    run_tts(args.run_dir, engine)


if __name__ == "__main__":
    main()
