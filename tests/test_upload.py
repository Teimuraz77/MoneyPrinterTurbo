import re
from pathlib import Path

import pytest

from wwnn.upload import metadata, youtube
from wwnn.upload.youtube import FakeYouTube, PrivacyViolation, VideoMeta

UPLOAD_DIR = Path(__file__).resolve().parent.parent / "wwnn" / "upload"


def _meta():
    return VideoMeta(title="WWNN: Goose", description="d", tags=["x"])


def test_body_is_private_and_discloses_synthetic_media():
    body = youtube.build_body(_meta())
    assert body["status"]["privacyStatus"] == "private"
    assert body["status"]["containsSyntheticMedia"] is True
    assert "publishAt" not in body["status"]


def test_assert_private_refuses_anything_else():
    body = youtube.build_body(_meta())
    for bad in ({"privacyStatus": "pub" + "lic"}, {"privacyStatus": "un" + "listed"},
                {"privacyStatus": "private", "publishAt": "2099-01-01T00:00:00Z"}, {}):
        with pytest.raises(PrivacyViolation):
            youtube._assert_private({**body, "status": bad})


def test_upload_reads_back_privacy(tmp_path):
    f = tmp_path / "a.mp4"
    f.write_bytes(b"\0")
    yt = FakeYouTube()
    res = youtube.upload(yt, f, _meta(), media_factory=lambda p: None)
    assert res["privacy_verified"] == "private"
    assert yt.inserted[0]["status"]["privacyStatus"] == "private"


def test_upload_raises_if_youtube_reports_other_privacy(tmp_path):
    f = tmp_path / "a.mp4"
    f.write_bytes(b"\0")
    with pytest.raises(PrivacyViolation):
        youtube.upload(FakeYouTube(report_privacy="pub" + "lic"), f, _meta(), media_factory=lambda p: None)


def test_no_other_privacy_values_in_upload_code():
    """Belt and braces: the upload package must not even contain the other privacy strings."""
    for py in UPLOAD_DIR.glob("*.py"):
        src = py.read_text()
        assert not re.search(r"\b(public|unlisted)\b", src, re.I), py.name
        assert "related_video" not in src


def test_short_description_links_video_a(settings):
    doc = {"episode_title": "WWNN: Geese", "episode_description": "x", "short_title": "From the Archive: Cheese",
           "short_hook": "Annika opened a file.",
           "sources": [{"slot": "N1", "title": "Goose", "url": "https://e.x/1"},
                       {"slot": "A1", "title": "Cheese", "source": "Parish newsletter, 1961"}]}
    a = metadata.video_a_meta(doc, settings)
    b = metadata.video_b_meta(doc, settings, "abc123XYZ00")
    assert "https://youtu.be/abc123XYZ00" in b.description
    assert "#Shorts" in b.title and len(b.title) <= 100
    assert "Goose" in a.description and "Cheese" in a.description
    assert "AI-generated" in a.description and "AI-generated" in b.description
