"""Telegram message texts (HTML parse mode)."""

from __future__ import annotations

import html


def _e(s) -> str:
    return html.escape(str(s or ""))


def fmt_s(seconds: float) -> str:
    seconds = int(round(seconds or 0))
    return f"{seconds // 60}:{seconds % 60:02d}"


def selection_text(run: dict, proposals: list[dict], deadline_local: str) -> str:
    lines = [f"<b>WWNN {_e(run['iso_week'])} \u2014 pick this week's stories</b>",
             "Tap to toggle. Order of taps = priority. Need \u2265 2 new + \u2265 1 archive.",
             "Annika's segment (= the Short) uses your top archive pick; extra archive picks are "
             "pulled in only if the episode runs short.", ""]
    for p in proposals:
        sample = " <i>[SAMPLE DATA]</i>" if p.get("is_sample") else ""
        link = f' <a href="{_e(p["url"])}">link</a>' if p.get("url") else ""
        lines.append(f"<b>{_e(p['slot'])}</b> {_e(p['title'])}{sample}{link}")
        if p.get("summary"):
            lines.append(f"   <i>{_e(p['summary'][:160])}</i>")
    lines += ["", f"Deadline: {_e(deadline_local)}"]
    return "\n".join(lines)[:4000]


def approval_text(run: dict, version: int, est: dict, real: dict, warnings: list[str]) -> str:
    lines = [f"<b>WWNN {_e(run['iso_week'])} \u2014 script v{version} + voices ready</b>",
             f"Tom: {fmt_s(real.get('tom', 0))} \u00b7 Annika (= Short): {fmt_s(real.get('annika', 0))} "
             f"\u00b7 Video A total \u2248 {fmt_s(real.get('total', 0))}",
             f"Short \u2248 {fmt_s(real.get('short', 0))} (limit 0:59)", "",
             "Full script attached. Listen to both voice tracks, then:",
             "\u2705 <b>Approve</b> starts the LongCat render (hours of GPU).",
             "\U0001F501 <b>Regenerate</b> rewrites the script. \u274c <b>Reject</b> cancels the week."]
    if warnings:
        lines += ["", "<b>Warnings</b>"] + [f"\u2022 {_e(w)}" for w in warnings[:12]]
    return "\n".join(lines)[:4000]


def review_text(run: dict, a_id: str, b_id: str, qc: list[str], dry_run: bool) -> str:
    studio = "https://studio.youtube.com/video/{}/edit"
    lines = [f"<b>WWNN {_e(run['iso_week'])} uploaded \u2014 both videos are PRIVATE</b>",
             f"A (episode): {studio.format(a_id)}", f"B (Short): {studio.format(b_id)}", "",
             "<b>Review checklist</b>",
             "\u2610 Watch A and B (both private).",
             "\u2610 Publish or schedule <b>A</b> (or set it to unlisted) in Studio.",
             "\u2610 On <b>B</b>: Studio \u2192 Content \u2192 the Short \u2192 <b>Related video \u2192 A</b>. "
             "(No API exists for this; A must be public or unlisted first; needs advanced features.)",
             f"\u2610 Pin a comment on A: \u201cAnnika's archive rant as a Short: https://youtube.com/shorts/{_e(b_id)}\u201d",
             "\u2610 Confirm \u201cAltered or synthetic content = Yes\u201d, then publish B."]
    if qc:
        lines += ["", "<b>QC notes</b>"] + [f"\u2022 {_e(q)}" for q in qc]
    if dry_run:
        lines.insert(1, "<i>DRY RUN: nothing was uploaded; IDs are fake.</i>")
    return "\n".join(lines)[:4000]


def failure_text(run: dict, stage: str, error: str) -> str:
    return (f"\U0001F6A8 <b>WWNN {_e(run['iso_week'])} failed in {_e(stage)}</b>\n"
            f"<pre>{_e(error[-1500:])}</pre>\nFix the cause, then tap Resume (or run "
            f"<code>wwnn resume {run['id']}</code>).")[:4000]
