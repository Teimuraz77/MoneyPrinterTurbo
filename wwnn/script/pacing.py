"""Duration estimates and the dynamic pacing budget for Video A and the Short.

Constraints (all configurable):
  * Video A total runtime (bumpers + Tom + Annika) in [video_a_min_s, video_a_max_s] (3-5 min).
  * Annika's segment is rendered once and reused as the Short, so its speech is capped at
    ``annika_max_speech_s`` such that  short_intro + annika + CTA card <= short_max_s (< 60 s).
  * Because Annika is capped, the dynamic pacing rule fills time like this:
      1. Tom covers every selected breaking story.
      2. If the episode is short and Annika has headroom, pull a 2nd/3rd selected archive story
         into her segment (still within her cap) - "pull 1 to 2 archive stories".
      3. Otherwise ask Tom to expand his stories; if too long, drop the lowest-ranked live story.
"""

from __future__ import annotations

from dataclasses import dataclass

from wwnn.config import Settings
from wwnn.script.text import count_words, split_sentences


def estimate_seconds(text: str, wpm: float, sentence_pause: float) -> float:
    sentences = split_sentences(text)
    return count_words(text) / wpm * 60.0 + sentence_pause * max(0, len(sentences) - 1)


def estimate_part(segments: list[dict], wpm: float, settings: Settings) -> float:
    if not segments:
        return 0.0
    speech = sum(estimate_seconds(s["text"], wpm, settings.tts_sentence_pause_s) for s in segments)
    return speech + settings.tts_segment_pause_s * (len(segments) - 1)


def words_for_seconds(seconds: float, wpm: float) -> int:
    # ~12 % of the time goes to pauses between sentences/segments
    return max(20, int(seconds * 0.88 * wpm / 60.0))


@dataclass
class Budget:
    bumpers_s: float            # intro + transition + outro
    target_total_s: float       # what we aim for (inside [min, max])
    annika_cap_s: float         # hard cap (Short constraint)

    @classmethod
    def from_settings(cls, settings: Settings, bumpers_s: float, short_intro_s: float = 0.0) -> "Budget":
        cap = min(settings.annika_max_speech_s,
                  settings.short_max_s - settings.cta_seconds - short_intro_s - 0.5)
        target = settings.video_a_min_s + 0.4 * (settings.video_a_max_s - settings.video_a_min_s)
        return cls(bumpers_s=bumpers_s, target_total_s=target, annika_cap_s=cap)

    def total(self, tom_s: float, annika_s: float) -> float:
        return self.bumpers_s + tom_s + annika_s


def check(settings: Settings, budget: Budget, tom_s: float, annika_s: float) -> list[str]:
    """Return human-readable pacing problems (empty list = all good)."""
    problems = []
    total = budget.total(tom_s, annika_s)
    if total < settings.video_a_min_s:
        problems.append(f"Video A too short: {total:.0f}s < {settings.video_a_min_s:.0f}s")
    if total > settings.video_a_max_s:
        problems.append(f"Video A too long: {total:.0f}s > {settings.video_a_max_s:.0f}s")
    if annika_s > budget.annika_cap_s:
        problems.append(f"Annika/Short segment too long: {annika_s:.1f}s > {budget.annika_cap_s:.1f}s")
    return problems
