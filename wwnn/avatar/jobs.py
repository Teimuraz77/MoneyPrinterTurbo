"""Shot planning for LongCat: split each anchor's TTS track into render units.

LongCat-Video-Avatar 1.5 (25 fps): the first segment is 93 frames (3.72 s); every
continuation adds 80 new frames (3.2 s) on 13 conditioning frames. A shot is a contiguous
same-anchor stretch, cut in the pauses between segments (or sentences), capped at
``max_shot_s``, with cut points quantised to whole frames so concatenated shots stay in
sync with the original audio track.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

FPS = 25
FIRST_FRAMES = 93
NEW_FRAMES_PER_CONT = 80


def num_segments(duration_s: float) -> int:
    first = FIRST_FRAMES / FPS
    cont = NEW_FRAMES_PER_CONT / FPS
    return 1 + math.ceil(max(0.0, duration_s - first) / cont - 1e-9)


def frames_rendered(n_segments: int) -> int:
    return FIRST_FRAMES + (n_segments - 1) * NEW_FRAMES_PER_CONT


@dataclass
class Shot:
    key: str
    anchor: str
    start: float
    end: float
    segment_idxs: list[int]

    @property
    def duration(self) -> float:
        return round(self.end - self.start, 3)

    @property
    def num_segments(self) -> int:
        return num_segments(self.duration)

    def to_dict(self) -> dict:
        return {**asdict(self), "duration": self.duration, "num_segments": self.num_segments}


def _q(t: float) -> float:
    return round(round(t * FPS) / FPS, 3)


def plan_shots(track: dict, anchor: str, max_shot_s: float) -> list[Shot]:
    """``track`` is one entry of tts/manifest.json["tracks"]."""
    total = track["duration"]
    # candidate cut points: middle of every pause, tagged with "priority" (segment > sentence)
    units = []   # (start, end, segment idx)
    for seg in track["segments"]:
        for s in seg["sentences"]:
            units.append((s["start"], s["end"], seg["idx"]))
    if not units:
        return [Shot(f"{anchor}_01", anchor, 0.0, _q(total) or 0.04, [])]
    shots: list[Shot] = []
    cur_start = 0.0
    cur_units: list[tuple] = []
    for i, u in enumerate(units):
        if cur_units and (u[1] - cur_start) > max_shot_s:
            prev = cur_units[-1]
            # prefer cutting at a segment boundary inside the current shot if it is not too early
            cut_idx = len(cur_units) - 1
            for j in range(len(cur_units) - 1, 0, -1):
                if cur_units[j][2] != cur_units[j - 1][2] and (cur_units[j - 1][1] - cur_start) >= 0.6 * max_shot_s:
                    cut_idx = j - 1
                    break
            prev = cur_units[cut_idx]
            nxt = cur_units[cut_idx + 1] if cut_idx + 1 < len(cur_units) else u
            cut = _q((prev[1] + nxt[0]) / 2)
            shots.append(Shot(f"{anchor}_{len(shots) + 1:02d}", anchor, cur_start, cut,
                              sorted({x[2] for x in cur_units[:cut_idx + 1]})))
            cur_units = cur_units[cut_idx + 1:]
            cur_start = cut
        cur_units.append(u)
    shots.append(Shot(f"{anchor}_{len(shots) + 1:02d}", anchor, cur_start, _q(total) if _q(total) > cur_start else total,
                      sorted({x[2] for x in cur_units})))
    return shots
