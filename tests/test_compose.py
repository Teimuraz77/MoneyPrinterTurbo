import json
import subprocess

import pytest

from conftest import needs_ffmpeg
from wwnn.compose import audio, vhs
from wwnn.compose.fx import crop_portrait, esc


def test_osd_date():
    assert vhs.osd_date("1961-05-04") == "MAY. 04 1961"          # camcorder-style OSD date
    assert vhs.osd_date("c. 1897") == "C. 1897"
    assert vhs.osd_date("") == ""


def test_filter_paths_with_special_characters_are_refused():
    assert esc("/tmp/plain_path.ass") == "/tmp/plain_path.ass"
    for bad in ("/tmp/a:b.ass", "/tmp/it's.ass", "/tmp/a b.ass"):
        with pytest.raises(ValueError):
            esc(bad)
    assert "crop=" in crop_portrait(0.5)


def _probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format",
                          str(path)], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


@needs_ffmpeg
def test_vhs_filter_renders(tmp_path, settings):
    src = tmp_path / "in.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=320x240:r=25:d=1", "-pix_fmt",
                    "yuv420p", str(src)], check=True)
    chain = vhs.vhs_filter(320, 240, font=settings.mono_font_file, work_dir=tmp_path / "w", date_text="MAY 04 1961")
    out = tmp_path / "out.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(src), "-vf", chain, "-pix_fmt", "yuv420p", str(out)], check=True)
    st = _probe(out)["streams"][0]
    assert (st["width"], st["height"]) == (320, 240)


@needs_ffmpeg
def test_mix_ducks_and_normalises(tmp_path):
    prog = tmp_path / "prog.wav"
    bed = tmp_path / "bed.wav"
    # 2 s speech-like tone, 2 s silence, 2 s tone
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                    "aevalsrc='if(between(t,2,4),0,0.5*sin(2*PI*220*t))':s=48000:d=6", "-ac", "2", str(prog)], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=f=660:d=6:sample_rate=48000", "-ac", "2",
                    str(bed)], check=True)
    out = tmp_path / "mix.wav"
    audio.mix(prog, [{"path": str(bed), "start": 0.0, "end": 6.0, "volume": 0.5}], out, total=6.0, target_lufs=-14.0)
    assert out.exists()
    assert abs(audio.measure_lufs(out) - (-14.0)) < 1.5
