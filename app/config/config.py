"""Minimal configuration shim for the MoneyPrinterTurbo modules kept in the WWNN fork.

Upstream MPT's config.py managed a large, mutable ``config.toml`` for its WebUI and
dozens of commercial providers. WWNN only keeps MPT's subtitle logic, so this shim
exposes just what those modules read (``whisper``, ``log_level``, ``app``) and takes
the values from environment variables (``WWNN_WHISPER_*``). It never writes files.
"""

import os

root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

whisper = {
    "model_size": os.environ.get("WWNN_WHISPER_MODEL", "large-v3"),
    "device": os.environ.get("WWNN_WHISPER_DEVICE", "cpu"),
    "compute_type": os.environ.get("WWNN_WHISPER_COMPUTE_TYPE", "int8"),
    "language": os.environ.get("WWNN_WHISPER_LANGUAGE", "en"),
    "initial_prompt": os.environ.get("WWNN_WHISPER_INITIAL_PROMPT", ""),
}
app = {"ffmpeg_path": os.environ.get("WWNN_FFMPEG", "")}
log_level = os.environ.get("WWNN_LOG_LEVEL", "INFO")
ffmpeg_path = app["ffmpeg_path"]
