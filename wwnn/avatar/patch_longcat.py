"""Apply WWNN's small, env-controlled patches to LongCat's official avatar script.

Writes ``run_demo_avatar_single_audio_to_video_wwnn.py`` next to the upstream file and never
modifies upstream code. Every patch is anchored on an exact snippet from upstream commit
6b3f4b8; if the upstream script changes, patching FAILS LOUDLY instead of silently skipping.
All patches default to upstream behaviour when their env var is unset. See PATCHES.md.

  WWNN_LONGCAT_SEED=<int>            replaces the hard-coded seed 42
  WWNN_LONGCAT_OFFLOAD_KV_CACHE=1    passes offload_kv_cache=True to generate_avc (KV cache in RAM)
  WWNN_LONGCAT_SKIP_VOCAL_SEP=1      skips the Kim_Vocal_2 separator (clean TTS input needs none)
  WWNN_LONGCAT_SAVE_FINAL_ONLY=1     encodes only the final continuation instead of re-encoding the
                                     whole accumulated video after every segment (O(n^2) -> O(n))
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

UPSTREAM_NAME = "run_demo_avatar_single_audio_to_video.py"
PATCHED_NAME = "run_demo_avatar_single_audio_to_video_wwnn.py"

HEADER_ANCHOR = "from audio_separator.separator import Separator\n"
HEADER = '''
# ---- WWNN patch header (see wwnn/avatar/PATCHES.md) ----
import shutil as _wwnn_shutil
_WWNN_SKIP_SEP = os.environ.get("WWNN_LONGCAT_SKIP_VOCAL_SEP", "0") == "1"
_WWNN_SAVE_FINAL_ONLY = os.environ.get("WWNN_LONGCAT_SAVE_FINAL_ONLY", "0") == "1"
_WWNN_OFFLOAD_KV = os.environ.get("WWNN_LONGCAT_OFFLOAD_KV_CACHE", "0") == "1"
_WWNN_SEED = int(os.environ.get("WWNN_LONGCAT_SEED", "42"))


def _wwnn_copy_speech(src, dst):
    _wwnn_shutil.copyfile(src, dst)
    return dst
# ---- end WWNN patch header ----
'''

PATCHES: list[tuple[str, str, str]] = [
    ("seed", "    global_seed = 42\n", "    global_seed = _WWNN_SEED\n"),
    ("kv-offload", "            offload_kv_cache=False,\n", "            offload_kv_cache=_WWNN_OFFLOAD_KV,\n"),
    ("skip-separator-init", "    vocal_separator = Separator(\n",
     "    vocal_separator = None if _WWNN_SKIP_SEP else Separator(\n"),
    ("skip-separator-load", "    vocal_separator.load_model(audio_separator_model_name)\n",
     "    if vocal_separator is not None:\n        vocal_separator.load_model(audio_separator_model_name)\n"),
    ("skip-separator-run",
     '        temp_vocal_path = extract_vocal_from_speech(raw_speech_path, f"/tmp/temp_speech_{generate_random_uid()}_{global_rank}_vocal.wav", vocal_separator, audio_output_dir_temp)\n',
     '        _wwnn_tmp = f"/tmp/temp_speech_{generate_random_uid()}_{global_rank}_vocal.wav"\n'
     '        temp_vocal_path = _wwnn_copy_speech(raw_speech_path, _wwnn_tmp) if _WWNN_SKIP_SEP else '
     'extract_vocal_from_speech(raw_speech_path, _wwnn_tmp, vocal_separator, audio_output_dir_temp)\n'),
    ("save-final-only",
     "        if cp_rank == 0:\n            output_tensor = torch.from_numpy(np.array(all_generated_frames))\n",
     "        if cp_rank == 0 and (not _WWNN_SAVE_FINAL_ONLY or segment_idx + 1 == num_segments):\n"
     "            output_tensor = torch.from_numpy(np.array(all_generated_frames))\n"),
]


class PatchError(RuntimeError):
    pass


def patch_source(src: str) -> str:
    if src.count(HEADER_ANCHOR) != 1:
        raise PatchError("header anchor not found exactly once")
    out = src.replace(HEADER_ANCHOR, HEADER_ANCHOR + HEADER, 1)
    for name, old, new in PATCHES:
        n = out.count(old)
        if n != 1:
            raise PatchError(f"patch '{name}': anchor found {n} times (expected 1); upstream changed?")
        out = out.replace(old, new, 1)
    compile(out, PATCHED_NAME, "exec")  # syntax check
    return out


def patch_repo(repo_dir: str | Path) -> Path:
    repo_dir = Path(repo_dir)
    src = (repo_dir / UPSTREAM_NAME).read_text(encoding="utf-8")
    dst = repo_dir / PATCHED_NAME
    dst.write_text(patch_source(src), encoding="utf-8")
    return dst


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("repo_dir")
    args = ap.parse_args(argv)
    try:
        print(f"patched -> {patch_repo(args.repo_dir)}")
    except PatchError as e:
        print(f"LongCat patch failed: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
