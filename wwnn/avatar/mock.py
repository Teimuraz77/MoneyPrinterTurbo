"""Dry-run stand-in for LongCat: the static anchor PNG + an audio waveform 'mouth' + a label.
Produces footage at the same bucket resolution and 25 fps LongCat would."""

from __future__ import annotations

from pathlib import Path

from wwnn.util import ffmpeg, video_size

BUCKETS = {"480p": {"landscape": (832, 480), "portrait": (480, 832)},
           "720p": {"landscape": (1280, 768), "portrait": (768, 1280)}}


def bucket_for(image: Path, resolution: str) -> tuple[int, int]:
    from PIL import Image

    with Image.open(image) as im:
        w, h = im.size
    return BUCKETS[resolution]["landscape" if w >= h else "portrait"]


def mock_render(image: Path, wav: Path, out: Path, duration: float, resolution: str, label: str,
                font: Path | None = None) -> Path:
    w, h = bucket_for(image, resolution)
    draw = ""
    if font and Path(font).exists():
        draw = (f",drawtext=fontfile='{font}':text='MOCK RENDER {label}':x=12:y=12:fontsize={h // 24}:"
                f"fontcolor=white@0.8:box=1:boxcolor=black@0.4")
    fc = (f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,fps=25,format=yuv420p{draw}[bg];"
          f"[1:a]aformat=channel_layouts=mono,showwaves=s={w // 4}x{h // 8}:mode=cline:colors=white@0.9:rate=25[wv];"
          f"[bg][wv]overlay=x=(W-w)/2:y=H*0.62:shortest=1,format=yuv420p[v]")
    out.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg(["-loop", "1", "-framerate", "25", "-i", image, "-i", wav, "-filter_complex", fc, "-map", "[v]",
            "-t", f"{duration:.3f}", "-r", "25", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
            "-pix_fmt", "yuv420p", "-an", out])
    assert video_size(out) == (w, h)
    return out
