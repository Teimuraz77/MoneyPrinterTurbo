"""Private-only YouTube uploader (official YouTube Data API v3, ``videos.insert``).

SAFETY: this module knows exactly one privacy value. It is hard-coded, asserted before the
request is built, asserted again right before the call, stored in SQLite behind a CHECK
constraint, and READ BACK from YouTube after the upload. ``publishAt`` (scheduled
auto-publishing) is refused. There is deliberately no ``videos.update`` code path, and the
OAuth scopes (upload + readonly) cannot change privacy or delete anything.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

PRIVACY = "private"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube.readonly"]
FORBIDDEN_STATUS_KEYS = {"publishAt"}
TOKEN_URI = "https://oauth2.googleapis.com/token"


class PrivacyViolation(RuntimeError):
    pass


@dataclass
class VideoMeta:
    title: str
    description: str
    tags: list[str] = field(default_factory=list)
    category_id: str = "23"
    language: str = "en"


def _assert_private(body: dict) -> None:
    st = body.get("status", {})
    if st.get("privacyStatus") != PRIVACY or FORBIDDEN_STATUS_KEYS & set(st):
        raise PrivacyViolation(f"refusing upload, status={st!r}")


def build_body(meta: VideoMeta) -> dict:
    body = {
        "snippet": {"title": meta.title[:100], "description": meta.description[:5000],
                    "tags": meta.tags[:30], "categoryId": meta.category_id,
                    "defaultLanguage": meta.language, "defaultAudioLanguage": meta.language},
        "status": {"privacyStatus": PRIVACY,
                   "selfDeclaredMadeForKids": False,
                   "containsSyntheticMedia": True,      # AI-generated presenters -> disclose
                   "embeddable": True, "license": "youtube"},
    }
    _assert_private(body)
    return body


def credentials(settings):
    """OAuth user credentials from YOUTUBE_REFRESH_TOKEN (+ client id/secret) or the token file."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    if settings.youtube_refresh_token:
        creds = Credentials(None, refresh_token=settings.youtube_refresh_token, token_uri=TOKEN_URI,
                            client_id=settings.youtube_client_id, client_secret=settings.youtube_client_secret,
                            scopes=SCOPES)
    else:
        token_file = settings.path(settings.youtube_token_file)
        if not token_file.exists():
            raise RuntimeError("no YouTube credentials: set YOUTUBE_REFRESH_TOKEN or run `wwnn youtube auth`")
        creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)
    creds.refresh(Request())   # fails fast with invalid_grant if the token expired/was revoked
    return creds


def client(settings):
    from googleapiclient.discovery import build

    return build("youtube", "v3", credentials=credentials(settings), cache_discovery=False)


RETRYABLE = (500, 502, 503, 504)


def upload(yt, path: str | Path, meta: VideoMeta, *, max_retries: int = 8, media_factory=None) -> dict:
    """Upload privately; returns {"id", "privacy_verified"}. Raises PrivacyViolation on read-back mismatch."""
    body = build_body(meta)
    if media_factory is None:
        from googleapiclient.http import MediaFileUpload

        def media_factory(p):
            return MediaFileUpload(str(p), mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)
    _assert_private(body)                                     # re-check right before the call
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media_factory(path))
    resp, retry = None, 0
    while resp is None:
        try:
            _, resp = req.next_chunk()
        except Exception as e:  # googleapiclient.errors.HttpError / network errors
            status = getattr(getattr(e, "resp", None), "status", None)
            if (status in RETRYABLE or status is None) and retry < max_retries:
                retry += 1
                sleep = min(60, 2 ** retry) * random.uniform(0.5, 1.0)
                logger.warning(f"upload chunk failed ({e}); retry {retry} in {sleep:.0f}s")
                time.sleep(sleep)
                continue
            raise
    vid = resp["id"]
    items = yt.videos().list(part="status", id=vid).execute().get("items", [])
    verified = items[0]["status"]["privacyStatus"] if items else None
    if verified != PRIVACY:
        raise PrivacyViolation(f"video {vid} reports privacyStatus={verified!r} after upload - CHECK STUDIO NOW")
    logger.info(f"uploaded {path} -> {vid} ({verified})")
    return {"id": vid, "privacy_verified": verified}


class FakeYouTube:
    """In-memory stand-in for dry runs/tests. Records request bodies; never touches the network."""

    def __init__(self, report_privacy: str | None = None):
        self.inserted: list[dict] = []
        self.report_privacy = report_privacy
        self._n = 0

    def videos(self):
        return self

    def insert(self, part, body, media_body):
        self._n += 1
        self.inserted.append(body)
        vid = f"DRYRUN{self._n:05d}"
        privacy = self.report_privacy or body["status"]["privacyStatus"]
        self._store = getattr(self, "_store", {})
        self._store[vid] = privacy

        class _Req:
            def next_chunk(_self):
                return None, {"id": vid}
        return _Req()

    def list(self, part, id):
        store = self._store

        class _Req:
            def execute(_self):
                return {"items": [{"id": id, "status": {"privacyStatus": store[id]}}]}
        return _Req()
