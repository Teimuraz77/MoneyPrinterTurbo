# LongCat-Video patches applied by WWNN

WWNN calls LongCat's **official** single-audio avatar script as a subprocess. It does not
fork or vendor LongCat. At image build time, `python -m wwnn.avatar.patch_longcat
/opt/LongCat-Video` reads

    run_demo_avatar_single_audio_to_video.py      (upstream, meituan-longcat/LongCat-Video@6b3f4b8)

and writes a patched copy next to it:

    run_demo_avatar_single_audio_to_video_wwnn.py

The upstream file is never modified. Every patch is a literal search/replace anchored on
an exact snippet that must occur **exactly once**. If upstream changes the script, the
patcher raises `PatchError` and the Docker build fails, instead of silently producing a
half-patched script. `tests/test_avatar.py` checks this against a verbatim copy of the
pinned upstream file (`tests/fixtures/longcat_6b3f4b8_run_demo_avatar_single_audio_to_video.py.txt`).

All patches are **controlled by environment variables** and **default to upstream
behaviour** when the variable is unset. The runner (`wwnn/avatar/runner.py`) sets them per shot.

| Patch | Env var (set by runner) | Upstream behaviour | WWNN behaviour | Why |
|---|---|---|---|---|
| `seed` | `WWNN_LONGCAT_SEED` | `global_seed = 42` hard-coded | per-anchor seed (`LONGCAT_SEED_TOM/ANNIKA`) | Stable look per anchor across weeks |
| `kv-offload` | `WWNN_LONGCAT_OFFLOAD_KV_CACHE=1` | `offload_kv_cache=False` hard-coded in `generate_avc` | KV cache kept in system RAM | Fits 40–48 GB cards (reported OOM on 40 GB without it). `auto` = on below 70 GB VRAM |
| `skip-separator-*` (3 anchors) | `WWNN_LONGCAT_SKIP_VOCAL_SEP=1` | Every input WAV goes through `audio-separator` (Kim_Vocal_2 ONNX) | Input WAV copied as-is | TTS output is already clean speech. Saves time and avoids loading a model of unclear license |
| `save-final-only` | `WWNN_LONGCAT_SAVE_FINAL_ONLY=1` | Re-encodes the whole accumulated video after **every** continuation segment (O(n²) I/O) | Encodes only once, after the last segment | A 40 s shot (13 segments) no longer writes 13 growing MP4s |

Additionally, a small header is inserted after
`from audio_separator.separator import Separator`. It reads the env vars and defines a
copy helper.

## What is *not* patched

- Model loading, the INT8 loader (`--use_int8` → `base_model_int8`), the distill LoRA
  (`--use_distill`), `--model_type avatar-v1.5` and `--stage_1 ai2v` are used exactly as
  upstream ships them.
- Video continuation (`--num_segments`, `--ref_img_index`, `--mask_frame_range`) is
  upstream's own mechanism. The runner just picks `num_segments = 1 + ceil((D − 3.72) / 3.2)`.

## Low-VRAM profile (`LONGCAT_VRAM_PROFILE=lowmem24`)

Uses `run_demo_avatar_single_lowmem.py` from the **unmerged** community
[PR #115](https://github.com/meituan-longcat/LongCat-Video/pull/115), pinned to head commit
`f92256a4bcf32898592e2d3374b7ca0525fd5761`. It is fetched into the image only with
`--build-arg WITH_LOWMEM_PR=1`, together with `torchao` and `accelerate`. That script is
v1.5 + INT8 by construction and takes `--use_torchao`. WWNN does not patch it. It writes
`final_video.mp4`, which `find_output()` prefers. Expect it to be slow, and treat it as
experimental.

## Updating LongCat

1. Bump `LONGCAT_REF` in `docker/longcat.Dockerfile`.
2. Copy the new upstream script to the fixture and run `pytest tests/test_avatar.py`.
3. If a patch anchor moved, update `PATCHES` in `patch_longcat.py`. The test tells you
   which one.
