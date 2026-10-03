"""FFmpeg filtergraph helpers shared by the compositor."""

from __future__ import annotations

from pathlib import Path


_UNSAFE = set(":',;[]\\=% \"")


def esc(path: str | Path) -> str:
    """Absolute path for use as a filter option value. FFmpeg's nested filtergraph escaping is
    error-prone, so instead of escaping we refuse paths with special characters."""
    s = str(Path(path).resolve())
    bad = _UNSAFE & set(s)
    if bad:
        raise ValueError(f"path {s!r} contains characters unsafe for an FFmpeg filtergraph: {sorted(bad)}")
    return s


def fit(w: int, h: int, flags: str = "lanczos") -> str:
    """Scale-to-cover + centre-crop to exactly WxH (832x480 -> 1920x1080 crops ~2.5 % of height)."""
    return f"scale={w}:{h}:force_original_aspect_ratio=increase:flags={flags},crop={w}:{h},setsar=1"


def crop_portrait(crop_x: float = 0.5) -> str:
    """Cut a 9:16 window out of a landscape frame. crop_x is the window's horizontal centre (0..1)."""
    cx = min(max(crop_x, 0.0), 1.0)
    return f"crop=w='trunc(ih*9/16/2)*2':h=ih:x='max(0,min(iw-ow,iw*{cx:.4f}-ow/2))':y=0"


def x264(settings, extra_crf: int = 0) -> list[str]:
    return ["-c:v", "libx264", "-preset", settings.x264_preset, "-crf", str(settings.x264_crf + extra_crf),
            "-pix_fmt", "yuv420p", "-r", str(settings.fps), "-g", str(settings.fps * 2)]


PCM = ["-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2"]
