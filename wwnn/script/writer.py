"""Script writer: Ollama (or the dry-run mock) + lint/repair + the dynamic pacing loop."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

from wwnn.config import Settings
from wwnn.script import lint, pacing
from wwnn.script.schema import ANNIKA_SCHEMA, TOM_SCHEMA
from wwnn.util import StageError

PROMPTS = Path(__file__).parent / "prompts"


def load_prompt(name: str) -> str:
    return (PROMPTS / name).read_text(encoding="utf-8")


def prompt_hash() -> str:
    h = hashlib.sha256()
    for p in sorted(PROMPTS.glob("*.md")):
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


def _story_block(items: list[dict]) -> str:
    lines = []
    for it in items:
        date = f" (date: {it['event_date']})" if it.get("event_date") else ""
        lines.append(f"- [{it['slot']}] {it['title']}{date}\n  Facts: {it.get('summary') or '(headline only)'}\n"
                     f"  Source: {it.get('source') or 'unknown'}")
    return "\n".join(lines)


@dataclass
class PartRequest:
    anchor: str
    items: list[dict]
    target_words: int
    max_words: int = 0
    feedback: str = ""


@dataclass
class ScriptResult:
    doc: dict
    est: dict
    warnings: list[str] = field(default_factory=list)
    model: str = ""


class LLMBackend:
    """Ollama-backed writer."""

    def __init__(self, client, settings: Settings):
        self.client = client
        self.settings = settings
        self.model = client.model
        self.system = load_prompt("system_en.md")

    def write(self, req: PartRequest) -> dict:
        if req.anchor == "tom":
            n = max(1, len(req.items))
            intro, handover = 40, 25
            per_story = max(40, (req.target_words - intro - handover) // n)
            user = load_prompt("tom_en.md").format(
                stories=_story_block(req.items), target_words=req.target_words,
                words_per_story=per_story, intro_words=intro, handover_words=handover,
                feedback=req.feedback)
            return self.client.chat_json(self.system, user, TOM_SCHEMA)
        max_s = int(self.settings.annika_max_speech_s)
        user = load_prompt("annika_en.md").format(
            stories=_story_block(req.items), target_words=req.target_words,
            max_words=req.max_words, max_seconds=max_s, feedback=req.feedback)
        return self.client.chat_json(self.system, user, ANNIKA_SCHEMA)


def _segments(part: dict, anchor: str) -> list[dict]:
    out = []
    for s in part.get("segments", []):
        out.append({"anchor": anchor, "kind": s.get("kind"), "text": (s.get("text") or "").strip(),
                    "item_slot": s.get("item_slot"), "lower_third_title": s.get("lower_third_title"),
                    "lower_third_sub": s.get("lower_third_sub")})
    return out


def _write_part(backend, req: PartRequest, slots: set[str], repairs: int = 2) -> tuple[dict, list[dict], list[str]]:
    feedback = req.feedback
    last_errors: list[str] = []
    for attempt in range(repairs + 1):
        req.feedback = feedback + (("\n\nYOUR PREVIOUS ATTEMPT WAS REJECTED. Fix these problems:\n- " +
                                    "\n- ".join(last_errors)) if last_errors else "")
        part = backend.write(req)
        segs = _segments(part, req.anchor)
        res = lint.lint_part(segs, req.anchor, slots)
        if res.ok:
            return part, segs, res.warnings
        last_errors = res.errors
        logger.warning(f"{req.anchor} lint failed (attempt {attempt + 1}): {res.errors}")
    raise StageError(f"{req.anchor} script failed lint after {repairs + 1} attempts: {last_errors}")


def write_episode(backend, settings: Settings, live: list[dict], archive: list[dict], *,
                  bumpers_s: float, short_intro_s: float = 0.0, wpm: dict | None = None,
                  feedback: str = "") -> ScriptResult:
    """Write Tom + Annika with the dynamic pacing loop. ``live``/``archive`` are ranked selections."""
    if not live or not archive:
        raise StageError("need at least one live and one archive story")
    wpm = {"tom": settings.wpm_tom, "annika": settings.wpm_annika, **(wpm or {})}
    budget = pacing.Budget.from_settings(settings, bumpers_s, short_intro_s)
    annika_target_s = min(budget.annika_cap_s - 6, 40.0)
    annika_items = archive[:1]
    live_items = list(live)
    tom_target_s = max(60.0, budget.target_total_s - bumpers_s - annika_target_s)
    warnings: list[str] = []
    best = None

    for rnd in range(settings.pacing_max_rounds):
        tom_req = PartRequest("tom", live_items, pacing.words_for_seconds(tom_target_s, wpm["tom"]), feedback=feedback)
        ann_cap_words = pacing.words_for_seconds(budget.annika_cap_s, wpm["annika"])
        ann_req = PartRequest("annika", annika_items, min(ann_cap_words - 5,
                              pacing.words_for_seconds(annika_target_s, wpm["annika"])), ann_cap_words, feedback)
        tom_part, tom_segs, w1 = _write_part(backend, tom_req, {i["slot"] for i in live_items})
        ann_part, ann_segs, w2 = _write_part(backend, ann_req, {i["slot"] for i in annika_items})
        tom_s = pacing.estimate_part(tom_segs, wpm["tom"], settings)
        ann_s = pacing.estimate_part(ann_segs, wpm["annika"], settings)
        total = budget.total(tom_s, ann_s)
        problems = pacing.check(settings, budget, tom_s, ann_s)
        logger.info(f"pacing round {rnd + 1}: tom {tom_s:.0f}s annika {ann_s:.0f}s total {total:.0f}s {problems}")
        best = (tom_part, tom_segs, ann_part, ann_segs, tom_s, ann_s, w1 + w2, list(live_items), list(annika_items))
        if not problems:
            break
        if ann_s > budget.annika_cap_s:
            if len(annika_items) > 1 and ann_s - budget.annika_cap_s > 6:
                annika_items = annika_items[:-1]                          # give the extra story back
            annika_target_s = max(15.0, annika_target_s - (ann_s - budget.annika_cap_s) - 4)
        if total < settings.video_a_min_s:
            gap = settings.video_a_min_s - total
            headroom = budget.annika_cap_s - ann_s
            if headroom >= 12 and len(annika_items) < min(len(archive), 3):
                annika_items = archive[: len(annika_items) + 1]          # pull an extra archive story
                annika_target_s = min(budget.annika_cap_s - 4, ann_s + min(gap, headroom) )
                gap -= min(gap, headroom - 4)
            if gap > 0:
                tom_target_s += gap + 12
        elif total > settings.video_a_max_s:
            excess = total - settings.video_a_max_s
            if len(live_items) > 2 and excess > 25:
                live_items = live_items[:-1]                              # drop lowest-ranked story
            else:
                tom_target_s = max(60.0, tom_target_s - excess - 12)
    else:
        warnings.append("pacing did not converge: " + "; ".join(problems))

    tom_part, tom_segs, ann_part, ann_segs, tom_s, ann_s, lint_warnings, live_used, arch_used = best
    warnings += lint_warnings
    doc = {
        "episode_title": tom_part.get("episode_title", "WWNN").strip(),
        "episode_description": tom_part.get("episode_description", "").strip(),
        "short_title": ann_part.get("short_title", "From the Archive").strip(),
        "short_hook": ann_part.get("short_hook", "").strip(),
        "archive_date": arch_used[0].get("event_date") or "",
        "segments": tom_segs + ann_segs,
        "live_slots": [i["slot"] for i in live_used],
        "archive_slots": [i["slot"] for i in arch_used],
        "sources": [{"slot": i["slot"], "title": i["title"], "url": i.get("url"), "source": i.get("source"),
                     "is_sample": bool(i.get("is_sample"))} for i in live_used + arch_used],
    }
    full = lint.lint_episode(doc, set(doc["live_slots"]), set(doc["archive_slots"]))
    if not full.ok:
        raise StageError(f"episode lint failed: {full.errors}")
    est = {"tom_s": round(tom_s, 1), "annika_s": round(ann_s, 1), "bumpers_s": round(bumpers_s, 1),
           "total_s": round(budget.total(tom_s, ann_s), 1), "annika_cap_s": round(budget.annika_cap_s, 1)}
    return ScriptResult(doc=doc, est=est, warnings=warnings + full.warnings, model=getattr(backend, "model", "?"))
