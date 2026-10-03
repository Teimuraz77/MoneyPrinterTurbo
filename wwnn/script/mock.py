"""Deterministic offline writer for dry runs and tests (no LLM). Produces lint-clean text
of roughly the requested length so the pacing loop and the rest of the pipeline can be exercised."""

from __future__ import annotations

from wwnn.script.text import count_words

_TOM_FILLER = [
    "Officials have described the situation as under review, which is what officials say about weather.",
    "Nobody involved appears to have read the instructions, and frankly nobody blames them.",
    "A spokesperson said lessons would be learned, a phrase that has never once been true.",
    "I am told this is news. I have no reason to doubt it, and no energy to try.",
    "Experts are divided, mainly into those who care and those who have met the public.",
    "The local paper called it unprecedented, in the tone of a paper that has seen everything.",
]
_ANN_FILLER = [
    "Nobody learned anything, which I find almost reassuring.",
    "The files are quite clear, and nobody has ever asked to see them.",
    "Some of you will think this is new. It is filed under recurring.",
]


def _pad(base: str, target: int, filler: list[str], seed: int) -> str:
    text, i = base, seed
    while count_words(text) < target:
        text += " " + filler[i % len(filler)]
        i += 1
    return text


class MockBackend:
    model = "mock-writer"

    def __init__(self, settings=None):
        self.settings = settings

    def write(self, req) -> dict:
        n = max(1, len(req.items))
        if req.anchor == "tom":
            per = max(25, (req.target_words - 50) // n)
            segs = [{"kind": "intro", "text": "Good evening. This is Worldwide Weekly Nonsense News, and I am Tom "
                                             "Blunt. I have read this week's stories so that you do not have to, "
                                             "and I would like that noted."}]
            for k, it in enumerate(req.items):
                base = f"Our next story. {it['title']}. I have checked, and it is true, more or less."
                segs.append({"kind": "story", "item_slot": it["slot"], "text": _pad(base, per, _TOM_FILLER, k),
                             "lower_third_title": it["title"][:40], "lower_third_sub": "Apparently this is news"})
            segs.append({"kind": "handover", "text": "And because the present is evidently not enough: "
                                                     "From the Archive. Annika."})
            return {"episode_title": "WWNN: " + req.items[0]["title"][:60],
                    "episode_description": "Another week, another collection of things that happened anyway.",
                    "segments": segs}
        per = max(15, (min(req.target_words, req.max_words or 10**6) - 25) // n)
        segs = [{"kind": "archive_intro", "text": "How lovely of you to visit the archive. Do mind the dust."}]
        for k, it in enumerate(req.items):
            year = (it.get("event_date") or "")[:4] or "some time ago"
            base = f"In {year}, the following was reported. {it['title']}."
            segs.append({"kind": "archive_story", "item_slot": it["slot"], "text": _pad(base, per, _ANN_FILLER, k),
                         "lower_third_title": it["title"][:40], "lower_third_sub": f"Filed {year}"})
        segs.append({"kind": "signoff", "text": "That is all from the archive. Do put things back where you found them."})
        return {"short_title": "From the Archive: " + req.items[0]["title"][:50],
                "short_hook": "Annika has opened a file. You will not enjoy it.", "segments": segs}
