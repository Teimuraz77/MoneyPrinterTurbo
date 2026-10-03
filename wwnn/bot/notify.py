"""Outbound Telegram messages via the plain Bot API (requests). Used by the orchestrator and
stage containers; the interactive bot (``app.py``) only handles button presses and commands.
Without a token, messages are logged and appended to ``data/telegram_outbox.jsonl``."""

from __future__ import annotations

import json
from pathlib import Path

import requests
from loguru import logger

from wwnn.bot.keyboards import Rows, to_bot_api
from wwnn.util import utcnow


class Notifier:
    def __init__(self, token: str, chat_id: str, timeout: float = 60.0):
        self.base = f"https://api.telegram.org/bot{token}"
        self.chat_id = chat_id
        self.timeout = timeout

    def _call(self, method: str, data: dict, files: dict | None = None) -> dict:
        for attempt in range(3):
            try:
                if files:
                    r = requests.post(f"{self.base}/{method}", data=data, files=files, timeout=self.timeout * 3)
                else:
                    r = requests.post(f"{self.base}/{method}", json=data, timeout=self.timeout)
                body = r.json()
                if body.get("ok"):
                    return body["result"]
                logger.warning(f"telegram {method} failed: {body.get('description')}")
                if r.status_code < 500:
                    break
            except (requests.RequestException, ValueError) as e:
                logger.warning(f"telegram {method} error: {e}")
        return {}

    def send_message(self, text: str, buttons: Rows | None = None) -> int | None:
        data = {"chat_id": self.chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
        if buttons:
            data["reply_markup"] = to_bot_api(buttons)
        return self._call("sendMessage", data).get("message_id")

    def edit_message(self, message_id: int, text: str, buttons: Rows | None = None) -> None:
        data = {"chat_id": self.chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML",
                "disable_web_page_preview": True}
        if buttons:
            data["reply_markup"] = to_bot_api(buttons)
        self._call("editMessageText", data)

    def _send_file(self, method: str, field: str, path: Path, caption: str | None, buttons: Rows | None) -> int | None:
        data = {"chat_id": self.chat_id}
        if caption:
            data.update(caption=caption[:1000], parse_mode="HTML")
        if buttons:
            data["reply_markup"] = json.dumps(to_bot_api(buttons))
        with open(path, "rb") as f:
            return self._call(method, data, files={field: (Path(path).name, f)}).get("message_id")

    def send_document(self, path: Path, caption: str | None = None, buttons: Rows | None = None) -> int | None:
        return self._send_file("sendDocument", "document", path, caption, buttons)

    def send_audio(self, path: Path, caption: str | None = None, buttons: Rows | None = None) -> int | None:
        return self._send_file("sendAudio", "audio", path, caption, buttons)


class OutboxNotifier:
    """Offline notifier (dry runs, or no token configured)."""

    def __init__(self, outbox: Path):
        self.outbox = outbox
        self._n = 0

    def _write(self, kind: str, **payload) -> int:
        self._n += 1
        self.outbox.parent.mkdir(parents=True, exist_ok=True)
        with self.outbox.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": utcnow(), "kind": kind, "id": self._n, **payload}, ensure_ascii=False) + "\n")
        logger.info(f"[telegram outbox] {kind}: {(payload.get('text') or payload.get('path') or '')[:120]!r}")
        return self._n

    def send_message(self, text, buttons=None):
        return self._write("message", text=text, buttons=buttons)

    def edit_message(self, message_id, text, buttons=None):
        self._write("edit", message_id=message_id, text=text, buttons=buttons)

    def send_document(self, path, caption=None, buttons=None):
        return self._write("document", path=str(path), caption=caption, buttons=buttons)

    def send_audio(self, path, caption=None, buttons=None):
        return self._write("audio", path=str(path), caption=caption, buttons=buttons)


def make_notifier(settings):
    if settings.telegram_bot_token and settings.telegram_chat_id and (not settings.dry_run or settings.telegram_in_dry_run):
        return Notifier(settings.telegram_bot_token, settings.telegram_chat_id)
    return OutboxNotifier(settings.data_dir / "telegram_outbox.jsonl")
