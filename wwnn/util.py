"""Small shared helpers: hashing, JSON IO, time, subprocess + ffprobe wrappers."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any, Iterable

from loguru import logger


class StageError(RuntimeError):
    """A pipeline stage failed in a way that should surface in Telegram."""


def utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def sha256_file(path: str | Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def sha256_json(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: str | Path, obj: Any) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)
    return path


def run(cmd: list[str], *, timeout: float | None = None, cwd: str | Path | None = None,
        env: dict | None = None, quiet: bool = True) -> subprocess.CompletedProcess:
    """Run a command, raise StageError with the stderr tail on failure."""
    logger.debug("$ " + " ".join(shlex.quote(str(c)) for c in cmd))
    proc = subprocess.run([str(c) for c in cmd], cwd=cwd, env=env, timeout=timeout,
                          capture_output=quiet, text=True)
    if proc.returncode != 0:
        tail = (proc.stderr or "")[-2500:] if quiet else ""
        raise StageError(f"command failed ({proc.returncode}): {cmd[0]} ...\n{tail}")
    return proc


def ffmpeg_bin() -> str:
    return os.environ.get("WWNN_FFMPEG") or shutil.which("ffmpeg") or "ffmpeg"


def ffprobe_bin() -> str:
    return os.environ.get("WWNN_FFPROBE") or shutil.which("ffprobe") or "ffprobe"


def ffmpeg(args: Iterable[str], timeout: float | None = None) -> None:
    run([ffmpeg_bin(), "-hide_banner", "-nostdin", "-loglevel", "error", "-y", *args], timeout=timeout)


def probe(path: str | Path) -> dict:
    proc = run([ffprobe_bin(), "-v", "error", "-print_format", "json", "-show_format",
                "-show_streams", str(path)])
    return json.loads(proc.stdout)


def duration(path: str | Path) -> float:
    return float(probe(path)["format"]["duration"])


def video_size(path: str | Path) -> tuple[int, int]:
    for s in probe(path)["streams"]:
        if s.get("codec_type") == "video":
            return int(s["width"]), int(s["height"])
    raise StageError(f"no video stream in {path}")


def has_audio(path: str | Path) -> bool:
    return any(s.get("codec_type") == "audio" for s in probe(path)["streams"])


def iso_week(now: dt.date | None = None) -> str:
    y, w, _ = (now or dt.date.today()).isocalendar()
    return f"{y}-W{w:02d}"
