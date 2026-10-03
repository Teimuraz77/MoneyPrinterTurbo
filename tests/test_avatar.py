from pathlib import Path

import pytest

from wwnn.avatar import jobs, patch_longcat
from wwnn.avatar.runner import LongCatInvoker, find_output
from wwnn.util import StageError

FIXTURE = Path(__file__).parent / "fixtures" / "longcat_6b3f4b8_run_demo_avatar_single_audio_to_video.py.txt"


@pytest.mark.parametrize("dur,n", [(3.72, 1), (3.0, 1), (3.73, 2), (30, 10), (55, 18), (60, 19)])
def test_num_segments(dur, n):
    assert jobs.num_segments(dur) == n
    assert jobs.frames_rendered(n) / jobs.FPS >= dur - 1e-6


def _track(n_sent=30, sent_s=3.0, gap=0.4, per_seg=5):
    t, segs = 0.0, []
    for i in range(n_sent):
        if i % per_seg == 0:
            segs.append({"idx": len(segs), "sentences": []})
            if i:
                t += 0.4
        segs[-1]["sentences"].append({"start": round(t, 3), "end": round(t + sent_s, 3)})
        t += sent_s + gap
    return {"duration": round(t, 3), "segments": segs}


def test_shots_tile_the_track_without_gaps():
    tr = _track()
    shots = jobs.plan_shots(tr, "tom", max_shot_s=40.0)
    assert len(shots) >= 3
    assert shots[0].start == 0.0
    for a, b in zip(shots, shots[1:]):
        assert a.end == b.start                           # contiguous -> audio stays in sync
    assert abs(shots[-1].end - tr["duration"]) < 0.05
    for s in shots:
        assert s.duration <= 40.0 + 1e-6
        assert abs(s.start * jobs.FPS - round(s.start * jobs.FPS)) < 1e-6   # frame-quantised cuts
        # cut lands in a pause, never mid-sentence
        for seg in tr["segments"]:
            for sen in seg["sentences"]:
                assert not (sen["start"] < s.end < sen["end"])


def test_short_track_is_one_shot():
    shots = jobs.plan_shots(_track(n_sent=5), "annika", max_shot_s=40.0)
    assert len(shots) == 1 and shots[0].anchor == "annika"


def test_patch_applies_to_pinned_upstream():
    out = patch_longcat.patch_source(FIXTURE.read_text())
    for marker in ("WWNN_LONGCAT_SEED", "WWNN_LONGCAT_OFFLOAD_KV_CACHE", "WWNN_LONGCAT_SKIP_VOCAL_SEP",
                   "WWNN_LONGCAT_SAVE_FINAL_ONLY"):
        assert marker in out
    compile(out, "patched.py", "exec")


def test_patch_fails_loudly_when_upstream_changes():
    src = FIXTURE.read_text()
    with pytest.raises(patch_longcat.PatchError):
        patch_longcat.patch_source(src.replace("from audio_separator.separator import Separator\n", ""))
    name, old, _new = patch_longcat.PATCHES[0]
    with pytest.raises(patch_longcat.PatchError):
        patch_longcat.patch_source(src.replace(old, "# removed upstream\n"))


def test_patch_repo_writes_new_file(tmp_path):
    (tmp_path / patch_longcat.UPSTREAM_NAME).write_text(FIXTURE.read_text())
    dst = patch_longcat.patch_repo(tmp_path)
    assert dst.name == patch_longcat.PATCHED_NAME
    assert (tmp_path / patch_longcat.UPSTREAM_NAME).read_text() == FIXTURE.read_text()   # upstream untouched


def test_command_standard_profile(settings):
    cmd = LongCatInvoker(settings).command(Path("/w/in.json"), Path("/w/out"), 7, "480p")
    joined = " ".join(cmd)
    assert cmd[0] == "torchrun"
    assert "run_demo_avatar_single_audio_to_video_wwnn.py" in cmd
    for flag in ("--use_distill", "--use_int8", "--model_type avatar-v1.5", "--stage_1 ai2v",
                 "--resolution 480p", "--num_segments 7", "--input_json /w/in.json"):
        assert flag in joined


def test_command_lowmem24_profile(settings):
    settings.longcat_vram_profile = "lowmem24"
    cmd = LongCatInvoker(settings).command(Path("/w/in.json"), Path("/w/out"), 3, "480p")
    assert "run_demo_avatar_single_lowmem.py" in cmd and "--use_torchao" in cmd
    assert "--stage_1" in cmd and "ai2v" in cmd


def test_offload_and_annika_resolution(settings):
    settings.longcat_offload_kv_cache = "on"
    assert LongCatInvoker(settings).env(5)["WWNN_LONGCAT_OFFLOAD_KV_CACHE"] == "1"
    settings.longcat_offload_kv_cache = "off"
    env = LongCatInvoker(settings).env(5)
    assert env["WWNN_LONGCAT_OFFLOAD_KV_CACHE"] == "0" and env["WWNN_LONGCAT_SEED"] == "5"
    settings.longcat_resolution_annika = "720p"
    assert settings.anchor_resolution("annika") == "720p" and settings.anchor_resolution("tom") == "480p"


def test_find_output(tmp_path):
    with pytest.raises(StageError):
        find_output(tmp_path)
    for n in (1, 2, 10):
        (tmp_path / f"video_continue_{n}.mp4").write_bytes(b"x")
    (tmp_path / "video_continue_10-temp.mp4").write_bytes(b"x")
    assert find_output(tmp_path).name == "video_continue_10.mp4"
    (tmp_path / "final_video.mp4").write_bytes(b"x")                 # PR #115 output name wins
    assert find_output(tmp_path).name == "final_video.mp4"
