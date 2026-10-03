"""Deterministic script checks. Errors trigger a repair prompt; warnings go to Telegram."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from wwnn.ingest.safety import keyword_check
from wwnn.script.schema import ANNIKA_KINDS, STORY_KINDS, TOM_KINDS
from wwnn.script.text import count_words, split_sentences

HANDOVER_PHRASE = "from the archive"

_BRACKETS = re.compile(r"[\[\]{}()<>*_~`|]")
_SPEAKER = re.compile(r"^\s*(tom|annika|tom blunt|anchor|narrator|host|presenter)\s*:", re.I | re.M)
_EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F]")
_HASHTAG = re.compile(r"(^|\s)#\w")
_URL = re.compile(r"https?://|www\.|\.com\b|\.co\.uk\b", re.I)
_STAGE = re.compile(r"^(?:he |she |tom |annika )?(?:sighs?|laughs?|chuckles?|pauses?|beat|coughs?|"
                    r"clears (?:his |her )?throat|smiles?|shrugs?|music|applause|sfx|cut to)\W*$", re.I)


@dataclass
class LintResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def lint_text(text: str, where: str) -> LintResult:
    r = LintResult()
    if _BRACKETS.search(text):
        r.errors.append(f"{where}: brackets/asterisks/markup are not allowed (stage directions?)")
    if _SPEAKER.search(text):
        r.errors.append(f"{where}: speaker label found")
    if _EMOJI.search(text):
        r.errors.append(f"{where}: emoji found")
    if _HASHTAG.search(text):
        r.errors.append(f"{where}: hashtag found")
    if _URL.search(text):
        r.errors.append(f"{where}: URL found")
    for s in split_sentences(text):
        if _STAGE.match(s.strip()):
            r.errors.append(f"{where}: stage direction sentence {s!r}")
        if count_words(s) > 40:
            r.warnings.append(f"{where}: long sentence ({count_words(s)} words) may drift in TTS")
    verdict = keyword_check(text)
    if not verdict.safe:
        r.errors.append(f"{where}: TABOO - {verdict.reason}")
    return r


def lint_part(segments: list[dict], anchor: str, allowed_slots: set[str]) -> LintResult:
    res = LintResult()
    kinds = TOM_KINDS if anchor == "tom" else ANNIKA_KINDS
    for i, seg in enumerate(segments):
        where = f"{anchor}[{i}:{seg.get('kind')}]"
        if seg.get("kind") not in kinds:
            res.errors.append(f"{where}: kind not allowed for {anchor}")
        text = (seg.get("text") or "").strip()
        if count_words(text) < 3:
            res.errors.append(f"{where}: empty or too short")
        sub = lint_text(text, where)
        res.errors += sub.errors
        res.warnings += sub.warnings
        if seg.get("kind") in STORY_KINDS and seg.get("item_slot") not in allowed_slots:
            res.errors.append(f"{where}: item_slot {seg.get('item_slot')!r} is not a selected story")
        for k in ("lower_third_title", "lower_third_sub"):
            if seg.get(k) and _BRACKETS.search(seg[k]):
                res.warnings.append(f"{where}: odd characters in {k}")
    covered = {s.get("item_slot") for s in segments if s.get("kind") in STORY_KINDS}
    missing = allowed_slots - covered
    if missing:
        res.errors.append(f"{anchor}: stories not covered: {sorted(missing)}")
    if anchor == "tom":
        handovers = [s for s in segments if s.get("kind") == "handover"]
        if len(handovers) != 1:
            res.errors.append(f"tom: expected exactly one handover segment, got {len(handovers)}")
        elif segments[-1].get("kind") != "handover":
            res.errors.append("tom: the handover must be Tom's last segment")
        elif HANDOVER_PHRASE not in handovers[0]["text"].lower():
            res.errors.append('tom: handover must contain the phrase "From the Archive"')
        if not segments or segments[0].get("kind") != "intro":
            res.errors.append("tom: first segment must be the intro")
    else:
        if not segments or segments[0].get("kind") != "archive_intro":
            res.errors.append("annika: first segment must be archive_intro")
        if not segments or segments[-1].get("kind") != "signoff":
            res.errors.append("annika: last segment must be the signoff")
        joined = " ".join(s.get("text", "") for s in segments).lower()
        if re.search(r"\btom\b|rest of the (show|programme|episode)|next week", joined):
            res.errors.append("annika: must stand alone as a Short (no reference to Tom/rest of show/next week)")
    return res


def lint_episode(doc: dict, live_slots: set[str], archive_slots: set[str]) -> LintResult:
    segs = doc["segments"]
    tom = [s for s in segs if s["anchor"] == "tom"]
    ann = [s for s in segs if s["anchor"] == "annika"]
    res = LintResult()
    for part in (lint_part(tom, "tom", live_slots), lint_part(ann, "annika", archive_slots)):
        res.errors += part.errors
        res.warnings += part.warnings
    # after the handover only Annika speaks; Annika's segment is mandatory
    seen_handover = False
    for s in segs:
        if seen_handover and s["anchor"] != "annika":
            res.errors.append("after the handover only Annika may speak")
            break
        seen_handover |= s.get("kind") == "handover"
    if not ann:
        res.errors.append("Annika's archive segment is mandatory")
    return res
