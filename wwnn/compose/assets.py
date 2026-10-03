"""Generate tiny DUMMY placeholder assets so the pipeline can run end to end.

Every file written here is listed (with its sha256) in ``assets/PLACEHOLDERS.json``. Real
production runs warn in Telegram if any placeholder is still in use. Replace them with your
real Kling AI anchor PNGs, consented voice references, bumpers, lower-third templates and
licensed music - same paths, or point the WWNN_* path settings elsewhere.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from loguru import logger
from PIL import Image, ImageDraw, ImageFont

from wwnn.compose.fx import esc
from wwnn.config import Settings
from wwnn.tts.audio import fake_speech, write_wav
from wwnn.util import ffmpeg, sha256_file


def _font(path: Path, size: int):
    try:
        return ImageFont.truetype(str(path), size)
    except OSError:
        return ImageFont.load_default()


def _anchor_png(path: Path, w: int, h: int, bg: tuple, fg: tuple, label: str, font: Path) -> None:
    im = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(im)
    for i in range(0, h, 6):  # subtle backdrop texture
        d.line([(0, i), (w, i)], fill=tuple(max(0, c - 8) for c in bg))
    cx, cy = w // 2, int(h * 0.55)     # centred subject so the 9:16 Short crop keeps it
    d.ellipse([cx - h * 0.11, cy - h * 0.36, cx + h * 0.11, cy - h * 0.08], fill=fg)      # head
    d.rounded_rectangle([cx - h * 0.24, cy - h * 0.06, cx + h * 0.24, h + 40], radius=int(h * 0.08), fill=fg)
    d.text((40, 30), f"PLACEHOLDER - {label}", font=_font(font, h // 18), fill=(255, 255, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path)


def _lower_third(path: Path, w: int, h: int, bar: tuple, accent: tuple) -> None:
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    x0, y0, y1 = int(w * 0.05), int(h * 0.74), int(h * 0.88)
    d.rectangle([x0, y0, int(w * 0.62), y1], fill=bar)
    d.rectangle([x0, y0, x0 + int(w * 0.008), y1], fill=accent)
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path)


def _bumper(path: Path, w: int, h: int, seconds: float, color: str, text: str, font: Path, freq: int) -> None:
    txt = path.with_suffix(".txt")
    txt.write_text(text, encoding="utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg(["-f", "lavfi", "-i", f"color=c={color}:s={w}x{h}:r=25:d={seconds}",
            "-f", "lavfi", "-i", f"sine=f={freq}:d={seconds}:sample_rate=48000",
            "-vf", f"drawtext=fontfile={esc(font)}:textfile={esc(txt)}:x=(w-tw)/2:y=(h-th)/2:fontsize={h // 9}:fontcolor=white,"
                   f"fade=t=in:d=0.4,fade=t=out:st={seconds - 0.4}:d=0.4",
            "-af", f"volume=0.15,afade=t=in:d=0.3,afade=t=out:st={seconds - 0.5}:d=0.5",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "96k", "-shortest", path])
    txt.unlink(missing_ok=True)


def _bed(path: Path, seconds: float, freqs: list[float], seed: int) -> None:
    sr = 48000
    t = np.arange(int(seconds * sr)) / sr
    sig = sum(np.sin(2 * np.pi * f * t) for f in freqs) / len(freqs)
    trem = 0.75 + 0.25 * np.sin(2 * np.pi * 0.25 * t)
    rng = np.random.default_rng(seed)
    write_wav(path, 0.3 * sig * trem + 0.002 * rng.standard_normal(len(t)), sr)


def make_placeholders(settings: Settings, force: bool = False) -> list[Path]:
    font = settings.sans_font
    W, H = settings.video_a_width, settings.video_a_height
    targets = {
        "tom": settings.path(settings.tom_image), "annika": settings.path(settings.annika_image),
        "tom_voice": settings.path(settings.tom_voice_ref), "annika_voice": settings.path(settings.annika_voice_ref),
        "intro": settings.path(settings.bumper_intro), "transition": settings.path(settings.bumper_transition),
        "outro": settings.path(settings.bumper_outro), "lt_tom": settings.path(settings.lt_template_tom),
        "lt_annika": settings.path(settings.lt_template_annika), "bgm_news": settings.path(settings.bgm_news),
        "bgm_archive": settings.path(settings.bgm_archive),
    }
    made: list[Path] = []
    for key, p in targets.items():
        if p.exists() and not force:
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        if key == "tom":
            _anchor_png(p, 1920, 1080, (8, 52, 40), (30, 30, 34), "TOM BLUNT", font)
        elif key == "annika":
            _anchor_png(p, 1920, 1080, (112, 86, 56), (60, 44, 32), "ANNIKA", font)
        elif key.endswith("_voice"):
            write_wav(p, fake_speech(12.0, 24000, seed=7 if key == "tom_voice" else 11,
                                     pitch=115 if key == "tom_voice" else 205), 24000)
        elif key == "intro":
            _bumper(p, W, H, 3.0, "0x0b3d2e", "WWNN", font, 440)
        elif key == "transition":
            _bumper(p, W, H, 2.5, "0x5a4630", "FROM THE ARCHIVE", font, 330)
        elif key == "outro":
            _bumper(p, W, H, 3.0, "0x0b3d2e", "WWNN - same time next week", font, 392)
        elif key == "lt_tom":
            _lower_third(p, W, H, (6, 60, 45, 225), (210, 180, 60, 255))
        elif key == "lt_annika":
            _lower_third(p, W, H, (120, 96, 64, 230), (60, 40, 25, 255))
        elif key == "bgm_news":
            _bed(p, 30.0, [110.0, 164.8, 220.0], 1)
        elif key == "bgm_archive":
            _bed(p, 30.0, [98.0, 146.8, 196.0], 2)
        made.append(p)
        logger.info(f"placeholder written: {p}")
    manifest = settings.assets_dir / "PLACEHOLDERS.json"
    entries = json.loads(manifest.read_text()) if manifest.exists() else {}
    for p in made:
        entries[str(p)] = sha256_file(p)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(entries, indent=2))
    return made


def placeholders_in_use(settings: Settings) -> list[str]:
    manifest = settings.assets_dir / "PLACEHOLDERS.json"
    if not manifest.exists():
        return []
    out = []
    for path, digest in json.loads(manifest.read_text()).items():
        if Path(path).exists() and sha256_file(path) == digest:
            out.append(path)
    return out
