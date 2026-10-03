from wwnn.bot import handlers, keyboards
from wwnn.db import repo, seed
from wwnn.orchestrator.state import State

OWNER = 111


def _proposed_run(conn, week="2099-W05"):
    seed.seed_samples(conn)
    run_id = repo.create_run(conn, week)
    for i in range(1, 6):
        lid = repo.insert_live_item(conn, {"source": "test", "url": f"https://example.com/{i}",
                                           "title": f"Goose number {i} elected to council committee",
                                           "description": "harmless", "published_at": "2099-01-01T00:00:00Z",
                                           "url_hash": f"{week}u{i}", "title_hash": f"{week}t{i}", "safe": 1})
        repo.add_proposal(conn, run_id, f"N{i}", "live", lid)
    for i, a in enumerate(repo.archive_candidates(conn, 3), 1):
        repo.add_proposal(conn, run_id, f"A{i}", "archive", a["id"])
    repo.set_state(conn, run_id, State.AWAITING_SELECTION)
    return run_id


def test_callback_data_fits_telegram_limit(conn):
    run_id = 2_000_000_000
    props = [{"slot": f"N{i}", "title": "x" * 200} for i in range(1, 6)] + \
            [{"slot": f"A{i}", "title": "y" * 200} for i in range(1, 4)]
    rows = keyboards.selection_keyboard(run_id, props, ["N1", "A3"])
    rows += keyboards.approval_keyboard(run_id, 99) + keyboards.resume_keyboard(run_id)
    for row in rows:
        for label, data in row:
            assert len(data.encode()) <= 64
    api = keyboards.to_bot_api(rows)
    assert api["inline_keyboard"][0][0]["callback_data"] == f"t:{run_id}:N1"
    assert "\u2611" in rows[0][0][0] and "#1" in rows[0][0][0]     # checked + priority shown


def test_unauthorised_user_is_refused(conn, settings):
    run_id = _proposed_run(conn)
    r = handlers.handle_callback(conn, settings, 999, f"t:{run_id}:N1")
    assert r.alert and "authorised" in r.answer.lower()
    assert repo.selected_slots(conn, run_id) == []


def test_selection_toggle_and_confirm(conn, settings):
    run_id = _proposed_run(conn)
    r = handlers.handle_callback(conn, settings, OWNER, f"c:{run_id}")
    assert r.alert                                                      # nothing selected yet
    for slot in ("N2", "N1", "A3"):
        r = handlers.handle_callback(conn, settings, OWNER, f"t:{run_id}:{slot}")
        assert r.buttons_only
    assert repo.selected_slots(conn, run_id) == ["N2", "N1", "A3"]
    r = handlers.handle_callback(conn, settings, OWNER, f"c:{run_id}")
    assert "locked" in r.edit_text
    assert repo.get_run(conn, run_id)["state"] == State.SELECTED.value
    # double tap is harmless
    r = handlers.handle_callback(conn, settings, OWNER, f"c:{run_id}")
    assert "Already" in r.answer
    r = handlers.handle_callback(conn, settings, OWNER, f"t:{run_id}:N3")
    assert "closed" in r.answer.lower()


def _awaiting_approval(conn, version=1, week="2099-W05"):
    run_id = _proposed_run(conn, week)
    for s in ("N1", "N2", "A1"):
        repo.toggle_selection(conn, run_id, s)
    for st in (State.SELECTED, State.SCRIPTED, State.VOICED, State.AWAITING_APPROVAL):
        repo.set_state(conn, run_id, st)
    repo.save_script(conn, run_id, version, "mock", "h", {"segments": []}, 200.0, [])
    repo.update_run(conn, run_id, script_version=version)
    return run_id


def test_approve_moves_to_approved_only_for_current_version(conn, settings):
    run_id = _awaiting_approval(conn, version=2)
    r = handlers.handle_callback(conn, settings, OWNER, f"a:{run_id}:1")          # stale button
    assert r.alert and repo.get_run(conn, run_id)["state"] == State.AWAITING_APPROVAL.value
    r = handlers.handle_callback(conn, settings, OWNER, f"a:{run_id}:2")
    assert repo.get_run(conn, run_id)["state"] == State.APPROVED.value
    assert "LongCat" in r.edit_text
    r = handlers.handle_callback(conn, settings, OWNER, f"a:{run_id}:2")          # double tap
    assert r.alert


def test_regenerate_and_reject(conn, settings):
    run_id = _awaiting_approval(conn)
    handlers.handle_callback(conn, settings, OWNER, f"g:{run_id}:1")
    assert repo.get_run(conn, run_id)["state"] == State.SELECTED.value
    assert "rewrite" in repo.run_context(conn, run_id)["feedback"]
    run2 = _awaiting_approval(conn, week="2099-W06")
    handlers.handle_callback(conn, settings, OWNER, f"x:{run2}:1")
    assert repo.get_run(conn, run2)["state"] == State.CANCELLED.value


def test_resume_failed_run(conn, settings):
    run_id = _awaiting_approval(conn)
    repo.set_state(conn, run_id, State.APPROVED)
    repo.set_state(conn, run_id, State.FAILED, failed_stage=State.APPROVED.value, error="CUDA OOM")
    handlers.handle_callback(conn, settings, OWNER, f"rs:{run_id}")
    assert repo.get_run(conn, run_id)["state"] == State.APPROVED.value


def test_malformed_callbacks(conn, settings):
    for data in ("", "t", "t:abc", "zz:1", "a:1:x"):
        assert isinstance(handlers.handle_callback(conn, settings, OWNER, data), handlers.Reply)
