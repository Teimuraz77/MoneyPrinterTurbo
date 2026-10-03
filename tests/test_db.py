import sqlite3

import pytest

from wwnn.db import repo, seed
from wwnn.db.migrate import migrate, open_db
from wwnn.orchestrator.state import State


def test_migrate_idempotent(settings):
    c = open_db(settings.db_path)
    assert migrate(c) == []                     # second run applies nothing
    tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for t in ("archive_items", "live_items", "weekly_runs", "run_proposals", "selections", "scripts",
              "stage_checkpoints", "shots", "episodes", "uploads", "events"):
        assert t in tables


def test_seed_samples_are_marked(conn):
    n = seed.seed_samples(conn)
    assert n >= 5
    seed.seed_samples(conn)                       # re-seeding is an upsert, never duplicates
    rows = conn.execute("SELECT is_sample, title FROM archive_items").fetchall()
    assert len(rows) == n
    assert all(r["is_sample"] == 1 for r in rows)


def test_sample_archive_passes_taboo_screen(conn):
    from wwnn.ingest.safety import keyword_check
    seed.seed_samples(conn)
    for r in conn.execute("SELECT title, summary FROM archive_items"):
        assert keyword_check(r["title"] + " " + r["summary"]).safe, r["title"]


def _episode(conn):
    run_id = repo.create_run(conn, "2099-W02", dry_run=True)
    return repo.save_episode(conn, run_id, "A", path="/tmp/a.mp4", duration_s=200.0, width=1920, height=1080,
                             sha256="0" * 64)


def test_uploads_privacy_check_constraint(conn):
    ep = _episode(conn)
    up = repo.create_upload(conn, ep)
    row = conn.execute("SELECT privacy_sent FROM uploads WHERE id=?", (up,)).fetchone()
    assert row[0] == "private"
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE uploads SET privacy_sent='pub' || 'lic' WHERE id=?", (up,))


def test_state_and_selection_flow(conn):
    seed.seed_samples(conn)
    run_id = repo.create_run(conn, "2099-W03")
    arch = repo.archive_candidates(conn, 3)
    for i, a in enumerate(arch, 1):
        repo.add_proposal(conn, run_id, f"A{i}", "archive", a["id"])
    with pytest.raises(PermissionError):
        repo.toggle_selection(conn, run_id, "A1")        # not yet awaiting selection
    repo.set_state(conn, run_id, State.AWAITING_SELECTION)
    assert repo.toggle_selection(conn, run_id, "A2") == ["A2"]
    assert repo.toggle_selection(conn, run_id, "A1") == ["A2", "A1"]   # rank = tap order
    assert repo.toggle_selection(conn, run_id, "A2") == ["A1"]
    with pytest.raises(KeyError):
        repo.toggle_selection(conn, run_id, "N9")
    assert repo.validate_selection(["A1"]) is not None
    assert repo.validate_selection(["N1", "N2", "A1"]) is None
    # stale expected state -> False, not an exception
    assert repo.set_state(conn, run_id, State.SELECTED, expected=State.AWAITING_APPROVAL) is False


def test_checkpoints(conn):
    run_id = repo.create_run(conn, "2099-W04")
    repo.save_checkpoint(conn, run_id, "tts", "abc", {"x": 1})
    assert repo.get_checkpoint(conn, run_id, "tts")["inputs_hash"] == "abc"
    repo.clear_checkpoints(conn, run_id, ["tts"])
    assert repo.get_checkpoint(conn, run_id, "tts") is None
