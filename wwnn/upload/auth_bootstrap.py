"""One-time OAuth consent for the channel owner (run on a machine with a browser, or tunnel the port).

    python -m wwnn youtube auth

Uses YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET from .env (OAuth client type "Desktop app").
Writes the token to YOUTUBE_TOKEN_FILE (mode 0600). Set the OAuth consent screen to
"In production": in "Testing" status Google expires refresh tokens after 7 days.
"""

from __future__ import annotations

import os

from wwnn.upload.youtube import SCOPES, TOKEN_URI


def bootstrap(settings, port: int = 8765) -> str:
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not settings.youtube_client_id or not settings.youtube_client_secret:
        raise SystemExit("set YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET in .env first")
    flow = InstalledAppFlow.from_client_config({"installed": {
        "client_id": settings.youtube_client_id, "client_secret": settings.youtube_client_secret,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": TOKEN_URI,
        "redirect_uris": ["http://localhost"]}}, SCOPES)
    creds = flow.run_local_server(host="localhost", port=port, open_browser=False,
                                  authorization_prompt_message="Open this URL in your browser:\n{url}\n")
    path = settings.path(settings.youtube_token_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(creds.to_json())
    return str(path)
