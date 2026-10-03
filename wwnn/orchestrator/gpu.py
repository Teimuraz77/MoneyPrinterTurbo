"""One GPU owner at a time: a host-level file lock + unloading Ollama before heavy stages."""

from __future__ import annotations

import fcntl
import time
from contextlib import contextmanager
from pathlib import Path

from loguru import logger


@contextmanager
def gpu_stage(name: str, lock_path: Path, ollama=None, timeout_s: float = 6 * 3600):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w") as fh:
        t0 = time.time()
        while True:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.time() - t0 > timeout_s:
                    raise TimeoutError(f"GPU lock busy for {timeout_s}s ({name})")
                time.sleep(5)
        if ollama is not None:
            ollama.unload_all()
        logger.info(f"GPU acquired for {name}")
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)
