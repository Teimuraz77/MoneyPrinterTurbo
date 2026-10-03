"""Avatar stage: render every shot with LongCat-Video-Avatar 1.5 (or the dry-run mock).

Wraps LongCat's *official* single-audio inference script as a subprocess per shot:

    torchrun --nproc_per_node=1 run_demo_avatar_single_audio_to_video_wwnn.py \
        --checkpoint_dir <ckpt> --model_type avatar-v1.5 --use_distill --use_int8 \
        --stage_1 ai2v --resolution 480p --num_segments <n> --input_json <shot.json> ...

``--num_segments`` uses LongCat's built-in video continuation, so one subprocess renders a
whole shot of up to ``LONGCAT_MAX_SHOT_S`` seconds. Each finished shot is checkpointed (input
hash -> MP4) so a crash or OOM resumes at the next unfinished shot. VRAM profiles:

  standard  official INT8 + distill path; needs ~40-48 GB+ in practice (80 GB comfortable)
  offload   standard + KV-cache offload to system RAM (patched flag); for ~40-48 GB cards
  lowmem24  community PR #115 script (sequential offload + torchao); experimental 24 GB path
"""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import time
from pathlib import Path

from loguru import logger

from wwnn.avatar import jobs
from wwnn.avatar.mock import mock_render
from wwnn.config import Settings
from wwnn.util import StageError, duration, ffmpeg, read_json, sha256_file, sha256_json, write_json

OOM_MARKERS = ("CUDA out of memory", "OutOfMemoryError", "CUBLAS_STATUS_ALLOC_FAILED")


def gpu_total_mib() -> int | None:
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=20).stdout
        return min(int(x) for x in out.split() if x.strip().isdigit())
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


class LongCatInvoker:
    def __init__(self, settings: Settings):
        self.s = settings
        self.repo = Path(settings.longcat_repo_dir)

    def script(self) -> str:
        if self.s.longcat_script:
            return self.s.longcat_script
        if self.s.longcat_vram_profile == "lowmem24":
            return "run_demo_avatar_single_lowmem.py"            # from PR #115, fetched at image build
        return "run_demo_avatar_single_audio_to_video_wwnn.py"   # patched official script

    def offload_kv(self) -> bool:
        mode = self.s.longcat_offload_kv_cache
        if self.s.longcat_vram_profile == "offload" or mode == "on":
            return True
        if mode == "off":
            return False
        total = gpu_total_mib()
        return total is not None and total < 70_000

    def command(self, input_json: Path, out_dir: Path, n_segments: int, resolution: str) -> list[str]:
        s = self.s
        cmd = ["torchrun", f"--nproc_per_node={s.longcat_nproc}", "--master_port", str(29500 + os.getpid() % 1000),
               self.script(), "--checkpoint_dir", s.longcat_checkpoint_dir, "--input_json", str(input_json),
               "--output_dir", str(out_dir), "--resolution", resolution, "--num_segments", str(n_segments),
               "--stage_1", s.longcat_stage_1, "--ref_img_index", str(s.longcat_ref_img_index),
               "--mask_frame_range", str(s.longcat_mask_frame_range)]
        if s.longcat_vram_profile == "lowmem24" and not s.longcat_script:
            cmd += ["--use_torchao"]                               # PR #115 is v1.5 + INT8 by construction
        else:
            cmd += ["--model_type", s.longcat_model_type, "--context_parallel_size", str(s.longcat_context_parallel)]
            if s.longcat_use_distill:
                cmd.append("--use_distill")
            if s.longcat_use_int8:
                cmd.append("--use_int8")
        cmd += shlex.split(s.longcat_extra_args)
        return cmd

    def env(self, seed: int) -> dict:
        env = dict(os.environ)
        env.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
        env["WWNN_LONGCAT_SEED"] = str(seed)
        env["WWNN_LONGCAT_OFFLOAD_KV_CACHE"] = "1" if self.offload_kv() else "0"
        env["WWNN_LONGCAT_SKIP_VOCAL_SEP"] = "1" if self.s.longcat_skip_vocal_separation else "0"
        env["WWNN_LONGCAT_SAVE_FINAL_ONLY"] = "1"
        return env

    def render(self, shot: dict, image: Path, wav: Path, prompt: str, seed: int, work: Path) -> Path:
        work.mkdir(parents=True, exist_ok=True)
        input_json = write_json(work / "input.json", {"prompt": prompt, "cond_image": str(image),
                                                      "cond_audio": {"person1": str(wav)}})
        out_dir = work / "out"
        cmd = self.command(input_json, out_dir, shot["num_segments"], self.s.anchor_resolution(shot["anchor"]))
        log_path = work / "longcat.log"
        logger.info(f"LongCat {shot['key']}: {shot['duration']:.1f}s, {shot['num_segments']} segments")
        with open(log_path, "w") as log:
            proc = subprocess.run(cmd, cwd=self.repo, env=self.env(seed), stdout=log, stderr=subprocess.STDOUT,
                                  timeout=self.s.longcat_shot_timeout_s)
        tail = log_path.read_text(errors="replace")[-3000:]
        if proc.returncode != 0:
            kind = "CUDA OOM" if any(m in tail for m in OOM_MARKERS) else f"exit {proc.returncode}"
            raise StageError(f"LongCat failed on {shot['key']} ({kind}). Log tail:\n{tail[-1500:]}")
        return find_output(out_dir)


def find_output(out_dir: Path) -> Path:
    """Locate the final video written by the official script (or the PR #115 script)."""
    final = out_dir / "final_video.mp4"
    if final.exists():
        return final
    conts = sorted(out_dir.glob("video_continue_*.mp4"),
                   key=lambda p: int(p.stem.rsplit("_", 1)[-1]) if p.stem.rsplit("_", 1)[-1].isdigit() else -1)
    conts = [p for p in conts if not p.stem.endswith(("-temp", "-cropvideo"))]
    if conts:
        return conts[-1]
    for name in ("ai2v_demo_1.mp4", "at2v_demo_1.mp4", "segment_001.mp4"):
        if (out_dir / name).exists():
            return out_dir / name
    raise StageError(f"no LongCat output video found in {out_dir}")


def _conform(src: Path, dst: Path, dur: float) -> Path:
    """Exact-length, 25 fps, video-only copy (audio is re-attached from the TTS track later)."""
    ffmpeg(["-i", src, "-vf", "fps=25,tpad=stop_mode=clone:stop_duration=2,format=yuv420p", "-t", f"{dur:.3f}",
            "-an", "-c:v", "libx264", "-preset", "fast", "-crf", "16", dst])
    return dst


def run_avatar(run_dir: Path, settings: Settings, *, mock: bool, on_progress=None, conn=None, run_id=None) -> dict:
    tts = read_json(run_dir / "tts" / "manifest.json")
    av_dir = run_dir / "avatar"
    shots_dir = av_dir / "shots"
    shots_dir.mkdir(parents=True, exist_ok=True)
    invoker = None if mock else LongCatInvoker(settings)
    anchors = {
        "tom": (settings.path(settings.tom_image), settings.tom_prompt, settings.longcat_seed_tom),
        "annika": (settings.path(settings.annika_image), settings.annika_prompt, settings.longcat_seed_annika),
    }
    plan = {a: [s.to_dict() for s in jobs.plan_shots(tts["tracks"][a], a, settings.longcat_max_shot_s)]
            for a in ("tom", "annika")}
    write_json(av_dir / "plan.json", plan)
    all_shots = plan["tom"] + plan["annika"]
    total_segments = sum(s["num_segments"] for s in all_shots)
    logger.info(f"avatar plan: {len(all_shots)} shots, {total_segments} LongCat segments")
    params = {k: getattr(settings, k) for k in (
        "longcat_model_type", "longcat_stage_1", "longcat_use_distill", "longcat_use_int8", "longcat_vram_profile",
        "longcat_ref_img_index", "longcat_mask_frame_range", "longcat_script", "longcat_extra_args")}
    done_segments, t_start = 0, time.time()
    outputs: dict[str, list[str]] = {"tom": [], "annika": []}
    for idx, shot in enumerate(all_shots, 1):
        anchor = shot["anchor"]
        image, prompt, seed = anchors[anchor]
        if not image.exists():
            raise StageError(f"anchor image missing: {image}")
        wav = shots_dir / f"{shot['key']}.wav"
        ffmpeg(["-i", run_dir / "tts" / tts["tracks"][anchor]["wav"], "-ss", f"{shot['start']:.3f}",
                "-to", f"{shot['end']:.3f}", "-ar", "16000", "-ac", "1", wav])
        shot_hash = sha256_json({"wav": sha256_file(wav), "img": sha256_file(image), "prompt": prompt, "seed": seed,
                                 "res": settings.anchor_resolution(anchor), "params": params, "mock": mock,
                                 "dur": shot["duration"]})
        mp4 = shots_dir / f"{shot['key']}.mp4"
        side = shots_dir / f"{shot['key']}.json"
        if mp4.exists() and side.exists() and read_json(side).get("input_sha256") == shot_hash:
            logger.info(f"shot {shot['key']}: cached, skipping")
            outputs[anchor].append(str(mp4))
            done_segments += shot["num_segments"]
            continue
        if conn is not None:
            from wwnn.db import repo
            repo.upsert_shot(conn, run_id, shot["key"], anchor=anchor, audio_seconds=shot["duration"],
                             num_segments=shot["num_segments"], input_sha256=shot_hash, status="running")
        t0 = time.time()
        if mock:
            raw = mock_render(image, wav, shots_dir / f"{shot['key']}_raw.mp4", shot["duration"],
                              settings.anchor_resolution(anchor), shot["key"], Path(settings.mono_font_file))
        else:
            raw = invoker.render(shot, image, wav, prompt, seed, shots_dir / shot["key"])
        _conform(raw, mp4, shot["duration"])
        took = time.time() - t0
        write_json(side, {"input_sha256": shot_hash, "render_seconds": round(took, 1), **shot})
        if conn is not None:
            repo.upsert_shot(conn, run_id, shot["key"], mp4_path=str(mp4), render_seconds=took, status="done")
        outputs[anchor].append(str(mp4))
        done_segments += shot["num_segments"]
        elapsed = time.time() - t_start
        eta = elapsed / max(1, done_segments) * (total_segments - done_segments)
        write_json(av_dir / "progress.json", {"shot": idx, "shots": len(all_shots), "segments_done": done_segments,
                                              "segments_total": total_segments, "eta_s": round(eta)})
        if on_progress:
            on_progress(idx, len(all_shots), eta)

    result = {}
    for anchor in ("tom", "annika"):
        lst = av_dir / f"{anchor}_concat.txt"
        lst.write_text("".join(f"file '{Path(p).resolve()}'\n" for p in outputs[anchor]))
        out = av_dir / f"{anchor}.mp4"
        ffmpeg(["-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", out])
        result[anchor] = {"mp4": out.name, "duration": duration(out), "shots": plan[anchor]}
    write_json(av_dir / "manifest.json", result)
    return result


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="WWNN avatar stage (LongCat-Video-Avatar 1.5)")
    ap.add_argument("--run-dir", required=True, type=Path)
    ap.add_argument("--mock", action="store_true")
    args = ap.parse_args(argv)
    settings = Settings.from_env()
    run_avatar(args.run_dir, settings, mock=args.mock or settings.dry_run)


if __name__ == "__main__":
    main()
