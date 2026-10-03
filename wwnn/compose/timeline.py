"""Compositor: Video A (16:9 episode) and Video B (9:16 Short) from the rendered avatar footage.

Video A:  [intro bumper] [Tom + lower thirds + subs] [archive transition bumper]
          [Annika + retro lower thirds + HEAVY VHS + subs] [outro bumper]
Video B:  [optional 9:16 intro] [the SAME Annika render, cropped 9:16, same VHS, big subs] [CTA card]

Every part is rendered to an intermediate MKV with identical encode parameters (x264 + PCM),
concatenated losslessly, then the whole programme audio is mixed once with sidechain-ducked
music beds and two-pass loudness normalisation, and muxed to the final MP4 (AAC 192k).
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger
from PIL import Image, ImageDraw, ImageFont

from wwnn.compose import audio as audio_mod
from wwnn.compose import subtitles as subs
from wwnn.compose.fx import PCM, crop_portrait, esc, fit, x264
from wwnn.compose.lower_thirds import overlay_chain, render_lower_third
from wwnn.compose.vhs import osd_date, vhs_filter
from wwnn.config import Settings
from wwnn.util import StageError, duration, ffmpeg, has_audio, read_json, sha256_file, video_size, write_json

STORY_KINDS = {"story", "archive_story"}


def _subs_filter(ass: Path, settings: Settings) -> str:
    return f"ass={esc(ass)}:fontsdir={esc(settings.fonts_dir)}"


def normalize_clip(src: Path, out: Path, w: int, h: int, settings: Settings) -> float:
    """Bring a bumper to the common format (WxH, 25 fps, yuv420p, PCM stereo 48 kHz)."""
    if not src.exists():
        raise StageError(f"asset missing: {src}  (run `wwnn assets placeholders` for dummies)")
    d = duration(src)
    args = ["-i", src]
    if has_audio(src):
        amap = ["-map", "0:a:0", "-af", "aformat=sample_rates=48000:channel_layouts=stereo,apad"]
    else:
        args += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        amap = ["-map", "1:a"]
    ffmpeg([*args, "-map", "0:v:0", *amap, "-vf", f"{fit(w, h)},fps={settings.fps},format=yuv420p",
            "-t", f"{d:.3f}", *x264(settings), *PCM, out])
    return duration(out)


def _story_lower_thirds(track: dict, doc_segments: list[dict], anchor: str, out_dir: Path, w: int, h: int,
                        settings: Settings) -> list[dict]:
    tpl = settings.path(settings.lt_template_tom if anchor == "tom" else settings.lt_template_annika)
    title_font = settings.sans_font if anchor == "tom" else Path(settings.mono_font_file)
    items = []
    for seg in track["segments"]:
        doc_seg = doc_segments[seg["idx"]]
        if seg["kind"] not in STORY_KINDS or not doc_seg.get("lower_third_title"):
            continue
        start = seg["start"] + 0.5
        end = min(seg["end"], start + 6.0)
        if end - start < 1.5:
            continue
        png = render_lower_third(tpl, out_dir / f"lt_{anchor}_{seg['idx']:02d}.png", w, h,
                                 doc_seg["lower_third_title"], doc_seg.get("lower_third_sub") or "",
                                 title_font, Path(settings.mono_font_file) if anchor == "annika" else settings.sans_font)
        items.append({"png": png, "start": start, "end": end})
    return items


def render_anchor_part(*, video: Path, wav: Path, track: dict, out: Path, w: int, h: int, settings: Settings,
                       work: Path, portrait: bool, vhs: bool, lower_thirds: list[dict], date_text: str = "",
                       banner: str = "", subtitle_cues=None) -> float:
    dur = track["duration"]
    args = ["-i", video, "-i", wav]
    for lt in lower_thirds:
        args += ["-loop", "1", "-framerate", str(settings.fps), "-t", f"{dur:.3f}", "-i", lt["png"]]
    geo = (crop_portrait(settings.short_crop_x) + "," + fit(w, h)) if portrait else fit(w, h)
    fc = [f"[0:v]fps={settings.fps},{geo},format=yuv420p,tpad=stop_mode=clone:stop_duration=1[base]"]
    lt_fc, label = overlay_chain(2, lower_thirds)
    if lt_fc:
        fc.append(lt_fc)
    chain = []
    if vhs:
        chain.append(vhs_filter(w, h, font=settings.mono_font_file, work_dir=work / f"vhs_{out.stem}",
                                osd_text=settings.vhs_osd_text, date_text=date_text))
    if banner:  # drawn after the VHS filter so it stays legible
        bf = work / f"banner_{out.stem}.txt"
        bf.write_text(banner, encoding="utf-8")
        chain.append(f"drawtext=fontfile={esc(settings.mono_font_file)}:textfile={esc(bf)}:x=(w-tw)/2:y=h*0.14:"
                     f"fontsize={int(h * 0.026)}:fontcolor=white@0.92:box=1:boxcolor=black@0.45:boxborderw=12")
    cues = subtitle_cues if subtitle_cues is not None else subs.cues_from_track(track, portrait=portrait)
    ass = subs.write_ass(cues, work / f"{out.stem}.ass", w, h, portrait=portrait, font=settings.subtitle_font)
    subs.write_srt(cues, work / f"{out.stem}.srt")
    chain.append(_subs_filter(ass, settings))
    fc.append(f"[{label}]{','.join(chain)},format=yuv420p[v]")
    fc.append("[1:a]aformat=sample_rates=48000:channel_layouts=stereo,apad[a]")
    ffmpeg([*args, "-filter_complex", ";".join(fc), "-map", "[v]", "-map", "[a]", "-t", f"{dur:.3f}",
            *x264(settings), *PCM, out])
    return duration(out)


def render_cta_card(out: Path, w: int, h: int, seconds: float, settings: Settings, work: Path) -> float:
    """End card for the Short: VHS-treated archive background + crisp CTA text pointing to Video A."""
    bg = work / "cta_bg.png"
    Image.new("RGB", (w, h), (92, 70, 46)).save(bg)
    txt = work / "cta_text.png"
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    big = ImageFont.truetype(str(settings.sans_font), int(h * 0.055))
    mid = ImageFont.truetype(str(settings.sans_font), int(h * 0.030))
    small = ImageFont.truetype(str(settings.mono_font_file), int(h * 0.021))
    lines = [("FULL EPISODE", big, int(h * 0.36)), ("Tap the related video", mid, int(h * 0.46)),
             ("Worldwide Weekly Nonsense News", small, int(h * 0.53)), ("WWNN", big, int(h * 0.60))]
    for text, font, y in lines:
        tw = d.textlength(text, font=font)
        d.text(((w - tw) / 2, y), text, font=font, fill=(245, 236, 215, 255),
               stroke_width=max(1, h // 400), stroke_fill=(30, 20, 10, 255))
    im.save(txt)
    vhs = vhs_filter(w, h, font=settings.mono_font_file, work_dir=work / "vhs_cta", osd_text=settings.vhs_osd_text)
    fc = (f"[0:v]{fit(w, h)},fps={settings.fps},format=yuv420p,{vhs}[bg];"
          f"[1:v]format=rgba,fade=t=in:st=0:d=0.3:alpha=1[t];[bg][t]overlay=0:0,format=yuv420p[v]")
    ffmpeg(["-loop", "1", "-framerate", str(settings.fps), "-t", f"{seconds:.3f}", "-i", bg,
            "-loop", "1", "-framerate", str(settings.fps), "-t", f"{seconds:.3f}", "-i", txt,
            "-f", "lavfi", "-t", f"{seconds:.3f}", "-i", "anullsrc=r=48000:cl=stereo",
            "-filter_complex", fc, "-map", "[v]", "-map", "2:a",
            "-t", f"{seconds:.3f}", *x264(settings), *PCM, out])
    return duration(out)


def concat(parts: list[Path], out: Path) -> Path:
    lst = out.with_suffix(".txt")
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in parts))
    ffmpeg(["-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", out])
    return out


def finalize(programme: Path, beds: list[dict], out: Path, settings: Settings) -> dict:
    total = duration(programme)
    wav = out.with_name(out.stem + "_mix.wav")
    audio_mod.mix(programme, beds, wav, total=total, target_lufs=settings.target_lufs)
    ffmpeg(["-i", programme, "-i", wav, "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac",
            "-b:a", "192k", "-movflags", "+faststart", "-t", f"{total:.3f}", out])
    wav.unlink(missing_ok=True)
    w, h = video_size(out)
    return {"path": str(out), "duration": round(duration(out), 3), "width": w, "height": h,
            "lufs": round(audio_mod.measure_lufs(out), 1), "sha256": sha256_file(out)}


def _cues(settings: Settings, track: dict, wav: Path, doc: dict, anchor: str, portrait: bool, work: Path):
    if settings.subtitle_provider != "whisper":
        return None
    text = " ".join(s["text"] for s in doc["segments"] if s["anchor"] == anchor)
    try:
        cues = subs.whisper_cues(wav, text, work)
        if portrait:  # re-chunk long whisper cues for vertical video
            out = []
            for a, b, t in cues:
                parts = subs._chunks(t, 22, 4)
                step = (b - a) / max(1, len(parts))
                out += [(a + i * step, a + (i + 1) * step, p) for i, p in enumerate(parts)]
            return out
        return cues
    except Exception as e:  # never lose a render over subtitles
        logger.warning(f"whisper subtitles failed ({e}); using TTS timings")
        return None


def compose_all(run_dir: Path, settings: Settings, doc: dict) -> dict:
    tts = read_json(run_dir / "tts" / "manifest.json")
    av = read_json(run_dir / "avatar" / "manifest.json")
    work = run_dir / "compose"
    work.mkdir(parents=True, exist_ok=True)
    tracks = tts["tracks"]
    date_text = osd_date(doc.get("archive_date"))

    # ---------------- Video A ----------------
    W, H = settings.video_a_width, settings.video_a_height
    a_dir = work / "A"
    a_dir.mkdir(exist_ok=True)
    parts, timeline, t = [], {}, 0.0

    def add(name: str, path: Path, d: float):
        nonlocal t
        parts.append(path)
        timeline[name] = (round(t, 3), round(t + d, 3))
        t += d

    add("intro", a_dir / "00_intro.mkv",
        normalize_clip(settings.path(settings.bumper_intro), a_dir / "00_intro.mkv", W, H, settings))
    tom_lts = _story_lower_thirds(tracks["tom"], doc["segments"], "tom", a_dir, W, H, settings)
    add("tom", a_dir / "01_tom.mkv", render_anchor_part(
        video=run_dir / "avatar" / av["tom"]["mp4"], wav=run_dir / "tts" / tracks["tom"]["wav"], track=tracks["tom"],
        out=a_dir / "01_tom.mkv", w=W, h=H, settings=settings, work=a_dir, portrait=False, vhs=False,
        lower_thirds=tom_lts,
        subtitle_cues=_cues(settings, tracks["tom"], run_dir / "tts" / tracks["tom"]["wav"], doc, "tom", False, a_dir)))
    add("transition", a_dir / "02_transition.mkv",
        normalize_clip(settings.path(settings.bumper_transition), a_dir / "02_transition.mkv", W, H, settings))
    ann_lts = _story_lower_thirds(tracks["annika"], doc["segments"], "annika", a_dir, W, H, settings)
    ann_wav = run_dir / "tts" / tracks["annika"]["wav"]
    add("annika", a_dir / "03_annika.mkv", render_anchor_part(
        video=run_dir / "avatar" / av["annika"]["mp4"], wav=ann_wav, track=tracks["annika"],
        out=a_dir / "03_annika.mkv", w=W, h=H, settings=settings, work=a_dir, portrait=False, vhs=True,
        lower_thirds=ann_lts, date_text=date_text,
        subtitle_cues=_cues(settings, tracks["annika"], ann_wav, doc, "annika", False, a_dir)))
    add("outro", a_dir / "04_outro.mkv",
        normalize_clip(settings.path(settings.bumper_outro), a_dir / "04_outro.mkv", W, H, settings))
    prog_a = concat(parts, a_dir / "programme.mkv")
    beds_a = [{"path": settings.path(settings.bgm_news), "start": timeline["tom"][0], "end": timeline["tom"][1],
               "volume": settings.bgm_volume},
              {"path": settings.path(settings.bgm_archive), "start": timeline["annika"][0],
               "end": timeline["annika"][1], "volume": settings.bgm_volume}]
    video_a = finalize(prog_a, beds_a, work / "video_a.mp4", settings)
    video_a["timeline"] = timeline

    # ---------------- Video B (Short) ----------------
    SW, SH = settings.short_width, settings.short_height
    b_dir = work / "B"
    b_dir.mkdir(exist_ok=True)
    b_parts = []
    if settings.short_intro:
        normalize_clip(settings.path(settings.short_intro), b_dir / "00_intro.mkv", SW, SH, settings)
        b_parts.append(b_dir / "00_intro.mkv")
    render_anchor_part(
        video=run_dir / "avatar" / av["annika"]["mp4"], wav=ann_wav, track=tracks["annika"],
        out=b_dir / "01_annika.mkv", w=SW, h=SH, settings=settings, work=b_dir, portrait=True, vhs=True,
        lower_thirds=[], date_text=date_text, banner="WWNN - FROM THE ARCHIVE",
        subtitle_cues=_cues(settings, tracks["annika"], ann_wav, doc, "annika", True, b_dir))
    b_parts.append(b_dir / "01_annika.mkv")
    render_cta_card(b_dir / "02_cta.mkv", SW, SH, settings.cta_seconds, settings, b_dir)
    b_parts.append(b_dir / "02_cta.mkv")
    prog_b = concat(b_parts, b_dir / "programme.mkv")
    video_b = finalize(prog_b, [{"path": settings.path(settings.bgm_archive), "start": 0.0,
                                 "end": duration(prog_b), "volume": settings.bgm_volume}],
                       work / "video_b_short.mp4", settings)

    qc = qc_check(video_a, video_b, settings)
    manifest = {"A": video_a, "B": video_b, "qc": qc}
    write_json(work / "manifest.json", manifest)
    return manifest


def qc_check(a: dict, b: dict, settings: Settings) -> list[str]:
    warnings = []
    if not (a["width"], a["height"]) == (settings.video_a_width, settings.video_a_height):
        raise StageError(f"Video A has wrong size {a['width']}x{a['height']}")
    if not b["height"] > b["width"]:
        raise StageError("Short must be vertical (height > width)")
    if b["duration"] > min(59.5, settings.short_max_s + 0.5):
        raise StageError(f"Short is {b['duration']:.1f}s - must stay under 60 s")
    if not settings.video_a_min_s - 10 <= a["duration"] <= settings.video_a_max_s + 10:
        warnings.append(f"Video A runs {a['duration']:.0f}s (target {settings.video_a_min_s:.0f}-"
                        f"{settings.video_a_max_s:.0f}s)")
    for name, v in (("A", a), ("B", b)):
        if abs(v["lufs"] - settings.target_lufs) > 1.5:
            warnings.append(f"Video {name} loudness {v['lufs']} LUFS (target {settings.target_lufs})")
    return warnings
