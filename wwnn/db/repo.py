"""Data-access helpers. All state lives in SQLite so the bot and orchestrator can restart freely."""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from typing import Any, Iterable

from wwnn.orchestrator.state import State, check_transition
from wwnn.util import utcnow

# --------------------------------------------------------------------------- events

def add_event(conn: sqlite3.Connection, run_id: int | None, level: str, stage: str | None,
              message: str) -> None:
    conn.execute("INSERT INTO events (run_id, ts, level, stage, message) VALUES (?,?,?,?,?)",
                 (run_id, utcnow(), level, stage, message))


def events(conn, run_id: int, limit: int = 50) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM events WHERE run_id=? ORDER BY id DESC LIMIT ?",
                        (run_id, limit)).fetchall()

# --------------------------------------------------------------------------- archive

ARCHIVE_FIELDS = ("slug", "title", "summary", "event_date", "place", "source_citation",
                  "source_url", "rights_note", "tags", "absurdity", "verified_by", "verified_at",
                  "is_sample", "active")


def upsert_archive_item(conn, item: dict) -> int:
    data = {k: item.get(k) for k in ARCHIVE_FIELDS}
    if isinstance(data["tags"], (list, tuple)):
        data["tags"] = json.dumps(list(data["tags"]))
    data["is_sample"] = int(bool(data.get("is_sample")))
    data["active"] = 1 if data.get("active") is None else int(bool(data["active"]))
    cols = ",".join(data)
    qs = ",".join("?" for _ in data)
    upd = ",".join(f"{k}=excluded.{k}" for k in data if k != "slug")
    conn.execute(f"INSERT INTO archive_items ({cols}) VALUES ({qs}) "
                 f"ON CONFLICT(slug) DO UPDATE SET {upd}", tuple(data.values()))
    return conn.execute("SELECT id FROM archive_items WHERE slug=?", (data["slug"],)).fetchone()[0]


def archive_candidates(conn, n: int, cooldown_weeks: int = 26) -> list[sqlite3.Row]:
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(weeks=cooldown_weeks)).isoformat()
    return conn.execute(
        """SELECT * FROM archive_items WHERE active=1
           AND (last_used_at IS NULL OR last_used_at < ?)
           ORDER BY absurdity DESC, (last_used_at IS NOT NULL), last_used_at ASC, id ASC LIMIT ?""",
        (cutoff, n)).fetchall()


def get_archive_item(conn, item_id: int) -> sqlite3.Row:
    return conn.execute("SELECT * FROM archive_items WHERE id=?", (item_id,)).fetchone()

# --------------------------------------------------------------------------- live items

def insert_live_item(conn, item: dict) -> int | None:
    """Insert a scraped item; returns None if it is a duplicate (url or title hash)."""
    if conn.execute("SELECT 1 FROM live_items WHERE url_hash=? OR title_hash=?",
                    (item["url_hash"], item["title_hash"])).fetchone():
        return None
    cur = conn.execute(
        """INSERT INTO live_items (source,url,url_hash,title_hash,title,description,language,
           published_at,fetched_at,absurdity,safe,safety_reason)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (item["source"], item["url"], item["url_hash"], item["title_hash"], item["title"],
         item.get("description"), item.get("language"), item.get("published_at"), utcnow(),
         item.get("absurdity"), item.get("safe"), item.get("safety_reason")))
    return cur.lastrowid


def live_title_hashes(conn) -> list[str]:
    return [r[0] for r in conn.execute("SELECT title_hash FROM live_items")]


def set_live_safety(conn, item_id: int, safe: bool, absurdity: int | None, reason: str) -> None:
    conn.execute("UPDATE live_items SET safe=?, absurdity=?, safety_reason=?, "
                 "status=CASE WHEN ? THEN status ELSE 'rejected' END WHERE id=?",
                 (int(safe), absurdity, reason, int(safe), item_id))


def live_candidates(conn, n: int, days: int = 8) -> list[sqlite3.Row]:
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).isoformat()
    rows = conn.execute(
        """SELECT * FROM live_items WHERE status='candidate' AND safe=1 AND fetched_at >= ?
           ORDER BY absurdity DESC, fetched_at DESC""", (cutoff,)).fetchall()
    # source diversity: round-robin across sources, best first
    by_source: dict[str, list] = {}
    for r in rows:
        by_source.setdefault(r["source"], []).append(r)
    out: list = []
    while len(out) < n and any(by_source.values()):
        for src in list(by_source):
            if by_source[src] and len(out) < n:
                out.append(by_source[src].pop(0))
    return out


def get_live_item(conn, item_id: int) -> sqlite3.Row:
    return conn.execute("SELECT * FROM live_items WHERE id=?", (item_id,)).fetchone()

# --------------------------------------------------------------------------- runs

def create_run(conn, iso_week: str, dry_run: bool = False) -> int:
    now = utcnow()
    cur = conn.execute("INSERT INTO weekly_runs (iso_week, state, dry_run, created_at, updated_at) "
                       "VALUES (?,?,?,?,?)", (iso_week, State.CREATED.value, int(dry_run), now, now))
    add_event(conn, cur.lastrowid, "info", "create", f"run created for {iso_week}")
    return cur.lastrowid


def get_run(conn, run_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM weekly_runs WHERE id=?", (run_id,)).fetchone()


def active_run_for_week(conn, iso_week: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM weekly_runs WHERE iso_week=? AND state NOT IN "
                        "('CANCELLED','SKIPPED','FAILED') ORDER BY id DESC LIMIT 1",
                        (iso_week,)).fetchone()


def runs_in_states(conn, states: Iterable[State | str]) -> list[sqlite3.Row]:
    vals = [State(s).value for s in states]
    q = ",".join("?" for _ in vals)
    return conn.execute(f"SELECT * FROM weekly_runs WHERE state IN ({q}) ORDER BY id", vals).fetchall()


def set_state(conn, run_id: int, new: State | str, *, expected: State | str | None = None,
              **fields) -> bool:
    """Atomically move a run to ``new``. Returns False if ``expected`` no longer matches
    (e.g. a double-tapped Telegram button), raises on an illegal transition."""
    new = State(new)
    row = get_run(conn, run_id)
    if row is None:
        raise KeyError(run_id)
    if expected is not None and row["state"] != State(expected).value:
        return False
    check_transition(row["state"], new)
    sets = ["state=?", "updated_at=?"] + [f"{k}=?" for k in fields]
    cur = conn.execute(f"UPDATE weekly_runs SET {', '.join(sets)} WHERE id=? AND state=?",
                       (new.value, utcnow(), *fields.values(), run_id, row["state"]))
    if cur.rowcount:
        add_event(conn, run_id, "info", "state", f"{row['state']} -> {new.value}")
    return bool(cur.rowcount)


def update_run(conn, run_id: int, **fields) -> None:
    if not fields:
        return
    sets = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE weekly_runs SET {sets}, updated_at=? WHERE id=?",
                 (*fields.values(), utcnow(), run_id))


def run_context(conn, run_id: int) -> dict:
    return json.loads(get_run(conn, run_id)["context"] or "{}")


def update_context(conn, run_id: int, **values) -> dict:
    ctx = run_context(conn, run_id)
    ctx.update(values)
    update_run(conn, run_id, context=json.dumps(ctx))
    return ctx

# --------------------------------------------------------------------------- proposals/selection

def add_proposal(conn, run_id: int, slot: str, kind: str, item_id: int) -> None:
    conn.execute("INSERT OR REPLACE INTO run_proposals (run_id, slot, kind, live_id, archive_id) "
                 "VALUES (?,?,?,?,?)", (run_id, slot, kind, item_id if kind == "live" else None,
                                         item_id if kind == "archive" else None))
    table = "live_items" if kind == "live" else None
    if table:
        conn.execute("UPDATE live_items SET status='proposed' WHERE id=?", (item_id,))


def proposals(conn, run_id: int) -> list[dict]:
    rows = conn.execute(
        """SELECT p.slot, p.kind, p.live_id, p.archive_id,
                  COALESCE(l.title, a.title) AS title,
                  COALESCE(l.description, a.summary) AS summary,
                  COALESCE(l.url, a.source_url) AS url,
                  COALESCE(l.source, a.source_citation) AS source,
                  a.event_date AS event_date, a.is_sample AS is_sample
           FROM run_proposals p
           LEFT JOIN live_items l ON l.id = p.live_id
           LEFT JOIN archive_items a ON a.id = p.archive_id
           WHERE p.run_id=? ORDER BY p.kind DESC, p.slot""", (run_id,)).fetchall()
    return [dict(r) for r in rows]


def selected_slots(conn, run_id: int) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT slot FROM selections WHERE run_id=? ORDER BY rank", (run_id,))]


def toggle_selection(conn, run_id: int, slot: str) -> list[str]:
    run = get_run(conn, run_id)
    if run is None or run["state"] != State.AWAITING_SELECTION.value:
        raise PermissionError("selection is closed for this run")
    if not conn.execute("SELECT 1 FROM run_proposals WHERE run_id=? AND slot=?", (run_id, slot)).fetchone():
        raise KeyError(slot)
    if conn.execute("SELECT 1 FROM selections WHERE run_id=? AND slot=?", (run_id, slot)).fetchone():
        conn.execute("DELETE FROM selections WHERE run_id=? AND slot=?", (run_id, slot))
    else:
        nxt = conn.execute("SELECT COALESCE(MAX(rank),0)+1 FROM selections WHERE run_id=?",
                           (run_id,)).fetchone()[0]
        conn.execute("INSERT INTO selections VALUES (?,?,?,?)", (run_id, slot, nxt, utcnow()))
    return selected_slots(conn, run_id)


def set_selection(conn, run_id: int, slots: list[str]) -> None:
    conn.execute("DELETE FROM selections WHERE run_id=?", (run_id,))
    for i, s in enumerate(slots, 1):
        conn.execute("INSERT INTO selections VALUES (?,?,?,?)", (run_id, s, i, utcnow()))


def validate_selection(slots: list[str], min_live: int = 2, min_archive: int = 1) -> str | None:
    n_live = sum(1 for s in slots if s.startswith("N"))
    n_arch = sum(1 for s in slots if s.startswith("A"))
    if n_live < min_live or n_arch < min_archive:
        return f"Pick at least {min_live} new stories and {min_archive} archive story."
    return None


def selected_items(conn, run_id: int) -> dict[str, list[dict]]:
    """Selected stories in priority order, split into live and archive."""
    props = {p["slot"]: p for p in proposals(conn, run_id)}
    out: dict[str, list[dict]] = {"live": [], "archive": []}
    for slot in selected_slots(conn, run_id):
        p = props[slot]
        out[p["kind"]].append(p)
    return out

# --------------------------------------------------------------------------- scripts

def save_script(conn, run_id: int, version: int, model: str, prompt_hash: str, doc: dict,
                est_seconds: float, warnings: list[str]) -> int:
    cur = conn.execute(
        "INSERT INTO scripts (run_id, version, model, prompt_hash, json, est_seconds, lint_warnings) "
        "VALUES (?,?,?,?,?,?,?)",
        (run_id, version, model, prompt_hash, json.dumps(doc, ensure_ascii=False), est_seconds,
         json.dumps(warnings)))
    return cur.lastrowid


def latest_script(conn, run_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM scripts WHERE run_id=? ORDER BY version DESC LIMIT 1",
                        (run_id,)).fetchone()


def set_script_real_seconds(conn, script_id: int, seconds: float) -> None:
    conn.execute("UPDATE scripts SET real_seconds=? WHERE id=?", (seconds, script_id))


def approve_script(conn, run_id: int, version: int) -> None:
    conn.execute("UPDATE scripts SET approved=1, approved_at=? WHERE run_id=? AND version=?",
                 (utcnow(), run_id, version))

# --------------------------------------------------------------------------- checkpoints

def get_checkpoint(conn, run_id: int, stage: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM stage_checkpoints WHERE run_id=? AND stage=?",
                        (run_id, stage)).fetchone()


def save_checkpoint(conn, run_id: int, stage: str, inputs_hash: str, outputs: Any,
                    seconds: float | None = None) -> None:
    conn.execute("INSERT OR REPLACE INTO stage_checkpoints VALUES (?,?,?,?,?,?)",
                 (run_id, stage, inputs_hash, json.dumps(outputs), utcnow(), seconds))


def clear_checkpoints(conn, run_id: int, stages: Iterable[str]) -> None:
    for s in stages:
        conn.execute("DELETE FROM stage_checkpoints WHERE run_id=? AND stage=?", (run_id, s))

# --------------------------------------------------------------------------- shots

def get_shot(conn, run_id: int, shot_key: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM shots WHERE run_id=? AND shot_key=?", (run_id, shot_key)).fetchone()


def upsert_shot(conn, run_id: int, shot_key: str, **f) -> None:
    f["updated_at"] = utcnow()
    existing = get_shot(conn, run_id, shot_key)
    if existing:
        sets = ", ".join(f"{k}=?" for k in f)
        conn.execute(f"UPDATE shots SET {sets} WHERE run_id=? AND shot_key=?",
                     (*f.values(), run_id, shot_key))
    else:
        cols = ["run_id", "shot_key", *f]
        conn.execute(f"INSERT INTO shots ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})",
                     (run_id, shot_key, *f.values()))

# --------------------------------------------------------------------------- episodes/uploads

def save_episode(conn, run_id: int, video: str, **f) -> int:
    f.setdefault("created_at", utcnow())
    cols = ["run_id", "video", *f]
    upd = ", ".join(f"{k}=excluded.{k}" for k in f)
    conn.execute(f"INSERT INTO episodes ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)}) "
                 f"ON CONFLICT(run_id, video) DO UPDATE SET {upd}", (run_id, video, *f.values()))
    return conn.execute("SELECT id FROM episodes WHERE run_id=? AND video=?", (run_id, video)).fetchone()[0]


def get_episode(conn, run_id: int, video: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM episodes WHERE run_id=? AND video=?", (run_id, video)).fetchone()


def create_upload(conn, episode_id: int) -> int:
    # privacy_sent has a CHECK constraint: only 'private' can ever be stored.
    cur = conn.execute("INSERT INTO uploads (episode_id, privacy_sent, status) VALUES (?, 'private', 'uploading')",
                       (episode_id,))
    return cur.lastrowid


def finish_upload(conn, upload_id: int, youtube_id: str, privacy_verified: str) -> None:
    conn.execute("UPDATE uploads SET youtube_id=?, privacy_verified=?, uploaded_at=?, status='done' WHERE id=?",
                 (youtube_id, privacy_verified, utcnow(), upload_id))


def fail_upload(conn, upload_id: int, error: str) -> None:
    conn.execute("UPDATE uploads SET status='failed', error=? WHERE id=?", (error[:2000], upload_id))


def done_upload_for(conn, run_id: int, video: str) -> sqlite3.Row | None:
    return conn.execute(
        """SELECT u.* FROM uploads u JOIN episodes e ON e.id=u.episode_id
           WHERE e.run_id=? AND e.video=? AND u.status='done' ORDER BY u.id DESC LIMIT 1""",
        (run_id, video)).fetchone()


def mark_items_used(conn, run_id: int, archive_ids: list[int], live_ids: list[int]) -> None:
    now = utcnow()
    for aid in archive_ids:
        conn.execute("UPDATE archive_items SET times_used=times_used+1, last_used_at=? WHERE id=?", (now, aid))
    for lid in live_ids:
        conn.execute("UPDATE live_items SET status='used' WHERE id=?", (lid,))
