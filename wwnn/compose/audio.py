"""Final audio master: programme audio + music beds with REAL sidechain ducking + two-pass loudnorm.

Replaces MoneyPrinterTurbo's fixed ``bgm_volume`` gain. The bed drops ~15 dB under speech and
recovers in pauses; beds are only present in their own sections (news bed under Tom, archive
bed under Annika) and are faded at section edges. Bumper audio is never ducked.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from wwnn.util import StageError, ffmpeg_bin, run


def _bed_chain(idx: int, start: float, end: float, volume: float, label: str) -> str:
    dur = max(0.1, end - start)
    fade = min(1.5, dur / 4)
    return (f"[{idx}:a]aformat=sample_rates=48000:channel_layouts=stereo,atrim=0:{dur:.3f},asetpts=PTS-STARTPTS,"
            f"volume={volume},afade=t=in:d={fade:.2f},afade=t=out:st={dur - fade:.3f}:d={fade:.2f},"
            f"adelay={int(start * 1000)}|{int(start * 1000)}[{label}]")


def mix(programme: Path, beds: list[dict], out: Path, *, total: float, target_lufs: float = -14.0) -> Path:
    """``beds``: [{"path", "start", "end", "volume"}]. Output: 48 kHz stereo WAV at target LUFS."""
    raw = out.with_name(out.stem + "_raw.wav")
    inputs = ["-i", str(programme)]
    chains = []
    labels = []
    for i, b in enumerate(beds, 1):
        inputs += ["-stream_loop", "-1", "-i", str(b["path"])]
        chains.append(_bed_chain(i, b["start"], b["end"], b.get("volume", 0.25), f"bed{i}"))
        labels.append(f"[bed{i}]")
    fc = ["[0:a]aformat=sample_rates=48000:channel_layouts=stereo,asplit=2[prog][sc]"] + chains
    if labels:
        fc.append(f"{''.join(labels)}amix=inputs={len(labels)}:duration=longest:normalize=0,apad,"
                  f"atrim=0:{total:.3f}[beds]")
        fc.append("[beds][sc]sidechaincompress=threshold=0.02:ratio=12:attack=20:release=450:makeup=1[ducked]")
        fc.append("[prog][ducked]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[mix]")
    else:
        fc.append("[sc]anullsink;[prog]anull[mix]")
    run([ffmpeg_bin(), "-hide_banner", "-nostdin", "-loglevel", "error", "-y", *inputs, "-filter_complex",
         ";".join(fc), "-map", "[mix]", "-t", f"{total:.3f}", "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(raw)])
    loudnorm(raw, out, target_lufs)
    raw.unlink(missing_ok=True)
    return out


def loudnorm(src: Path, dst: Path, target: float = -14.0, tp: float = -1.5, lra: float = 11.0) -> dict:
    """Two-pass EBU R128 normalisation (measure, then apply linearly)."""
    p = run([ffmpeg_bin(), "-hide_banner", "-nostdin", "-i", str(src), "-af",
             f"loudnorm=I={target}:TP={tp}:LRA={lra}:print_format=json", "-f", "null", "-"])
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", p.stderr, re.S)
    if not m:
        raise StageError("loudnorm measurement failed")
    st = json.loads(m.group(0))
    af = (f"loudnorm=I={target}:TP={tp}:LRA={lra}:measured_I={st['input_i']}:measured_TP={st['input_tp']}:"
          f"measured_LRA={st['input_lra']}:measured_thresh={st['input_thresh']}:offset={st['target_offset']}:"
          f"linear=true,aresample=48000")
    run([ffmpeg_bin(), "-hide_banner", "-nostdin", "-loglevel", "error", "-y", "-i", str(src), "-af", af,
         "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(dst)])
    return st


def measure_lufs(path: Path) -> float:
    p = run([ffmpeg_bin(), "-hide_banner", "-nostdin", "-i", str(path), "-af", "ebur128=framelog=quiet",
             "-f", "null", "-"])
    m = re.findall(r"I:\s+(-?[\d.]+) LUFS", p.stderr)
    return float(m[-1]) if m else float("nan")
