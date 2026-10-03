import pytest

from wwnn.script import lint, pacing, text, writer
from wwnn.script.mock import MockBackend

LIVE = [{"slot": f"N{i}", "title": f"Council debates the colour of bench number {i}", "url": f"https://e.x/{i}",
         "source": "test"} for i in range(1, 5)]
ARCH = [{"slot": f"A{i}", "title": f"Village holds annual cheese rolling inquiry {i}", "event_date": f"19{60 + i}-05-01",
         "is_sample": 1} for i in range(1, 4)]


def _tom(handover="And now, From the Archive. Annika."):
    return [{"kind": "intro", "text": "Good evening, this is the news, regrettably."},
            {"kind": "story", "item_slot": "N1", "text": "A council has met about a bench. It went badly."},
            {"kind": "handover", "text": handover}]


def _ann(extra=""):
    return [{"kind": "archive_intro", "text": "Welcome to the archive, do wipe your feet."},
            {"kind": "archive_story", "item_slot": "A1", "text": "In nineteen sixty one, a cheese escaped." + extra},
            {"kind": "signoff", "text": "That is all. Put things back where you found them."}]


def test_lint_accepts_clean_parts():
    assert lint.lint_part(_tom(), "tom", {"N1"}).ok
    assert lint.lint_part(_ann(), "annika", {"A1"}).ok


def test_handover_phrase_required():
    r = lint.lint_part(_tom("Over to Annika then."), "tom", {"N1"})
    assert any("From the Archive" in e for e in r.errors)


@pytest.mark.parametrize("bad", [
    "[sighs] A council has met.", "*pauses* Indeed.", "TOM: Good evening everyone.",
    "Sighs.", "Visit www.example.com for more.", "What a day \U0001F602 truly.", "Two people died at the fair.",
])
def test_lint_rejects_stage_directions_and_taboo(bad):
    assert not lint.lint_text(bad, "x").ok


def test_annika_must_stand_alone_for_the_short():
    r = lint.lint_part(_ann(" Back to you, Tom."), "annika", {"A1"})
    assert not r.ok


def test_episode_requires_annika():
    doc = {"segments": [dict(s, anchor="tom") for s in _tom()]}
    r = lint.lint_episode(doc, {"N1"}, set())
    assert any("mandatory" in e for e in r.errors)


def test_text_normalisation():
    assert text.split_sentences("Mr. Smith arrived. He left!  Then what?") == ["Mr. Smith arrived.", "He left!",
                                                                               "Then what?"]
    out = text.normalize_for_tts("In 1987, 3 geese paid £20.")
    assert "nineteen eighty-seven" in out and "three" in out and "twenty pounds" in out
    assert text.number_to_words(115) == "one hundred and fifteen"


def test_budget_caps_annika_for_the_short(settings):
    b = pacing.Budget.from_settings(settings, bumpers_s=12.0)
    assert b.annika_cap_s <= settings.short_max_s - settings.cta_seconds
    assert b.annika_cap_s <= settings.annika_max_speech_s
    assert pacing.check(settings, b, 100.0, 40.0)                # 152 s -> too short
    assert not pacing.check(settings, b, 170.0, 40.0)
    assert any("Annika" in p for p in pacing.check(settings, b, 170.0, 70.0))


def test_writer_paces_episode_into_3_to_5_minutes(settings):
    res = writer.write_episode(MockBackend(), settings, LIVE, ARCH, bumpers_s=12.0)
    assert settings.video_a_min_s <= res.est["total_s"] <= settings.video_a_max_s
    assert res.est["annika_s"] <= res.est["annika_cap_s"]
    segs = res.doc["segments"]
    assert segs[-1]["anchor"] == "annika" and segs[-1]["kind"] == "signoff"
    handover = [s for s in segs if s["kind"] == "handover"]
    assert len(handover) == 1 and "from the archive" in handover[0]["text"].lower()
    assert res.doc["archive_slots"][0] == "A1"                   # top archive pick always leads


class ThinNewsBackend(MockBackend):
    """Tom cannot stretch thin live stories beyond ~90 s, like a well-behaved LLM would."""

    def write(self, req):
        if req.anchor == "tom":
            req = type(req)(req.anchor, req.items, min(req.target_words, 230), req.max_words, req.feedback)
        return super().write(req)


def test_writer_pulls_extra_archive_story_when_short(settings):
    """Breaking news comes out short -> extra archive stories are pulled into Annika's segment,
    but never beyond her cap (her segment is the Short)."""
    settings.annika_max_speech_s = 58          # cap = min(58, 59 - CTA - 0.5) = 55 s -> headroom for a 2nd item
    res = writer.write_episode(ThinNewsBackend(), settings, LIVE[:2], ARCH, bumpers_s=12.0)
    assert len(res.doc["archive_slots"]) >= 2
    assert res.doc["archive_slots"][0] == "A1"
    assert res.est["annika_s"] <= res.est["annika_cap_s"]


def test_writer_needs_both_parts(settings):
    with pytest.raises(Exception):
        writer.write_episode(MockBackend(), settings, LIVE, [], bumpers_s=12.0)
