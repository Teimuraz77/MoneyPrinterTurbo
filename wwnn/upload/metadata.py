"""Titles/descriptions for both uploads. Video A's URL goes into the Short's description
(there is no API field for the Shorts 'related video' link - that is a manual Studio step)."""

from __future__ import annotations

from wwnn.upload.youtube import VideoMeta

DISCLOSURE = ("Satire. WWNN's presenters Tom Blunt and Annika are fictional, AI-generated characters "
              "with synthetic voices. Stories are summarised from the sources listed.")
TAGS = ["WWNN", "Worldwide Weekly Nonsense News", "satire", "weird news", "comedy news", "deadpan"]


def _sources(doc: dict, kinds: str) -> str:
    lines = []
    for s in doc.get("sources", []):
        if s["slot"][0] in kinds:
            src = f" - {s['url']}" if s.get("url") else (f" - {s['source']}" if s.get("source") else "")
            lines.append(f"- {s['title']}{src}")
    return "\n".join(lines)


def video_a_meta(doc: dict, settings) -> VideoMeta:
    desc = [doc.get("episode_description", ""), "", "This week's stories:", _sources(doc, "N"), "",
            "From the Archive:", _sources(doc, "A"), "", DISCLOSURE]
    if settings.youtube_channel_url:
        desc += ["", f"Every week: {settings.youtube_channel_url}"]
    return VideoMeta(title=doc.get("episode_title") or "WWNN", description="\n".join(desc).strip(),
                     tags=TAGS, category_id=settings.youtube_category_id)


def video_b_meta(doc: dict, settings, video_a_id: str) -> VideoMeta:
    title = (doc.get("short_title") or "From the Archive")[:90]
    if "#shorts" not in title.lower():
        title = f"{title} #Shorts"
    desc = [doc.get("short_hook", ""), "", f"Full episode: https://youtu.be/{video_a_id}", "",
            "From the Archive:", _sources(doc, "A"), "", DISCLOSURE, "", "#Shorts #WWNN"]
    return VideoMeta(title=title[:100], description="\n".join(desc).strip(), tags=TAGS + ["Shorts"],
                     category_id=settings.youtube_category_id)
