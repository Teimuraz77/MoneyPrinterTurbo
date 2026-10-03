"""Subtitles: cues from exact TTS sentence timings (default) or MPT's Whisper path, written as
ASS (styled for 16:9 or 9:16) and burned with libass."""

from __future__ import annotations

import re
from pathlib import Path

from wwnn.script.text import count_words


def _chunks(text: str, max_chars: int, max_words: int | None) -> list[str]:
    words = text.split()
    out, cur = [], []
    for w in words:
        cand = " ".join(cur + [w])
        if cur and (len(cand) > max_chars or (max_words and len(cur) >= max_words)):
            out.append(" ".join(cur))
            cur = [w]
        else:
            cur.append(w)
    if cur:
        out.append(" ".join(cur))
    return out


def cues_from_track(track: dict, *, portrait: bool, offset: float = 0.0) -> list[tuple[float, float, str]]:
    """Split each TTS sentence into display cues, timing proportional to character count."""
    cues = []
    max_chars, max_words = (22, 4) if portrait else (84, None)  # 84 = two lines of ~42
    for seg in track["segments"]:
        for s in seg["sentences"]:
            parts = _chunks(s["text"], max_chars, max_words)
            total = sum(len(p) for p in parts) or 1
            t = s["start"]
            span = s["end"] - s["start"]
            for p in parts:
                d = span * len(p) / total
                cues.append((offset + t, offset + t + d, p))
                t += d
    return cues


def _ts(t: float) -> str:
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _ass_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", " ")


def write_ass(cues: list[tuple[float, float, str]], path: Path, w: int, h: int, *, portrait: bool,
              font: str = "Be Vietnam Pro") -> Path:
    if portrait:
        size, margin_v, outline, align = int(h * 0.040), int(h * 0.30), 5, 2   # ~62-70 % height, clear of Shorts UI
    else:
        size, margin_v, outline, align = int(h * 0.048), int(h * 0.05), 3, 2
    wrap = 0 if not portrait else 1
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: {wrap}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,{outline},1,{align},{int(w * 0.08)},{int(w * 0.08)},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [f"Dialogue: 0,{_ts(a)},{_ts(b)},Default,,0,0,0,,{_ass_escape(t)}" for a, b, t in cues if b > a]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_srt(cues: list[tuple[float, float, str]], path: Path) -> Path:
    """Also publishable as a YouTube caption file (uses MPT's SRT helpers + atomic writer)."""
    from app.utils.subtitle_writer import write_subtitle_file
    from app.utils.utils import text_to_srt

    body = "\n".join(text_to_srt(i, t, a, b) for i, (a, b, t) in enumerate(cues, 1)) + "\n"
    write_subtitle_file(str(path), body)
    return path


def whisper_cues(wav: Path, script_text: str, work: Path) -> list[tuple[float, float, str]]:
    """Optional: MoneyPrinterTurbo's faster-whisper path + script re-alignment (``correct()``)."""
    from app.services import subtitle as mpt_subtitle

    srt = work / (wav.stem + ".whisper.srt")
    mpt_subtitle.create(str(wav), str(srt))
    if not srt.exists():
        raise RuntimeError("whisper produced no subtitles (faster-whisper missing?)")
    mpt_subtitle.correct(str(srt), script_text)
    cues = []
    for _, span, text in mpt_subtitle.file_to_subtitles(str(srt)):
        a, b = (_parse_srt_ts(x) for x in span.split(" --> "))
        cues.append((a, b, text))
    return cues


def _parse_srt_ts(s: str) -> float:
    h, m, rest = s.strip().split(":")
    sec, ms = re.split(r"[,.]", rest)
    return int(h) * 3600 + int(m) * 60 + int(sec) + int(ms) / 1000


def words_in(track: dict) -> int:
    return sum(count_words(s["text"]) for seg in track["segments"] for s in seg["sentences"])
