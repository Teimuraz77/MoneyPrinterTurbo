"""Heavy VHS / retro look for Annika's archive segment (Video A) and the Short.

Tested on FFmpeg 7.1. Applied at the *output* resolution, so the 16:9 episode and the 9:16
Short get the identical treatment (scanline pitch, grain, chroma bleed, jitter, tracking band,
OSD). Subtitles are burned *after* this filter so they stay readable.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from wwnn.compose.fx import esc

_MONTHS = "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split()


def osd_date(event_date: str | None) -> str:
    """'1957-04-01' -> 'APR. 01 1957'; free text like 'c. 1897' is passed through upper-cased."""
    if not event_date:
        return ""
    try:
        d = dt.date.fromisoformat(event_date[:10])
        return f"{_MONTHS[d.month - 1]}. {d.day:02d} {d.year}"
    except ValueError:
        return event_date.upper()[:20]


def vhs_filter(w: int, h: int, *, font: str | Path, work_dir: Path, osd_text: str = "PLAY",
               date_text: str = "") -> str:
    """Return a comma-joined video filter chain (input must already be WxH, 25 fps)."""
    work_dir.mkdir(parents=True, exist_ok=True)
    play = work_dir / "osd_play.txt"
    play.write_text(f"{osd_text} \u25b6", encoding="utf-8")
    fs = max(14, int(min(w, h) * 0.05))
    pad_x, pad_y = int(w * 0.042), int(h * 0.055)
    band = max(6, h // 60)
    shift = max(2, w // 320)
    chain = [
        f"scale={max(2, w // 3 // 2 * 2)}:{max(2, h // 3 // 2 * 2)}:flags=area",   # low luma resolution
        "avgblur=sizeX=2:sizeY=1",                                                  # horizontal smear
        f"scale={w}:{h}:flags=bicubic",
        "format=yuv420p",
        f"chromashift=cbh=-{shift}:crh={shift}:edge=smear",                         # colour bleed
        "curves=preset=vintage",
        "eq=contrast=1.10:brightness=0.02:saturation=0.60:gamma=1.05",            # faded colour
        "tmix=frames=3:weights='1 0.45 0.2'",                                      # ghosting
        "noise=c0s=14:c0f=t+u:c1s=6:c1f=t:c2s=6:c2f=t",                             # tape grain
        f"drawbox=x=0:y='mod(t*{int(h * 0.21)},ih)':w=iw:h={band}:color=white@0.10:t=fill",  # tracking band
        "drawgrid=w=iw:h=4:t=1:c=black@0.30",                                       # scanlines
        f"crop=w=iw-{2 * pad_x // 3}:h=ih-{max(2, h // 90) * 2}:x='{pad_x // 3}+{max(1, w // 640)}*3*sin(n/2.3)':y={max(2, h // 90)}",
        f"scale={w}:{h}:flags=bicubic",                                             # horizontal jitter
        "vignette=angle=PI/5",
        f"drawtext=fontfile={esc(font)}:textfile={esc(play)}:x={pad_x}:y={pad_y}:fontsize={fs}:"
        "fontcolor=white@0.85:shadowcolor=black@0.6:shadowx=3:shadowy=3",
    ]
    if date_text:
        date_f = work_dir / "osd_date.txt"
        date_f.write_text(date_text, encoding="utf-8")
        chain.append(f"drawtext=fontfile={esc(font)}:textfile={esc(date_f)}:x=w-tw-{pad_x}:y=h-th-{int(pad_y * 1.2)}:"
                     f"fontsize={int(fs * 0.9)}:fontcolor=white@0.85:shadowcolor=black@0.6:shadowx=3:shadowy=3")
    chain.append("format=yuv420p")
    return ",".join(chain)
