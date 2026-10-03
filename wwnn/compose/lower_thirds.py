"""Render per-story lower-third PNGs (transparent RGBA) from a template + text with Pillow."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def _fit_font(draw, text: str, font_path: Path, size: int, max_w: int):
    while size > 10:
        try:
            f = ImageFont.truetype(str(font_path), size)
        except OSError:
            return ImageFont.load_default()
        if draw.textlength(text, font=f) <= max_w:
            return f
        size -= 2
    return ImageFont.truetype(str(font_path), size)


def render_lower_third(template: Path, out: Path, w: int, h: int, title: str, sub: str,
                       title_font: Path, sub_font: Path, color=(255, 255, 255), sub_color=(225, 225, 210)) -> Path:
    if template.exists():
        base = Image.open(template).convert("RGBA").resize((w, h))
    else:
        base = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(base)
    x = int(w * 0.068)
    max_w = int(w * 0.53)
    tf = _fit_font(d, title, title_font, int(h * 0.046), max_w)
    sf = _fit_font(d, sub, sub_font, int(h * 0.030), max_w)
    d.text((x, int(h * 0.752)), title, font=tf, fill=color)
    d.text((x, int(h * 0.818)), sub, font=sf, fill=sub_color)
    out.parent.mkdir(parents=True, exist_ok=True)
    base.save(out)
    return out


def overlay_chain(n_inputs_before: int, items: list[dict], fade: float = 0.3) -> tuple[str, str]:
    """Build overlay filters for LT PNG inputs. ``items``: [{"start": s, "end": e}] in input order.
    Returns (filter text consuming [base], output label)."""
    parts, label = [], "base"
    for i, it in enumerate(items):
        inp = n_inputs_before + i
        st, en = it["start"], it["end"]
        parts.append(f"[{inp}:v]format=rgba,fade=t=in:st={st:.2f}:d={fade}:alpha=1,"
                     f"fade=t=out:st={max(st, en - fade):.2f}:d={fade}:alpha=1[lt{i}]")
        parts.append(f"[{label}][lt{i}]overlay=0:0:enable='between(t,{st:.2f},{en:.2f})'[ov{i}]")
        label = f"ov{i}"
    return ";".join(parts), label
