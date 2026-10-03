"""Button/command logic, independent of python-telegram-bot so it can be unit tested.
Every handler re-validates against SQLite (state + script version), so stale or double-tapped
buttons are harmless."""

from __future__ import annotations

from dataclasses import dataclass

from wwnn.bot import keyboards, texts
from wwnn.db import repo
from wwnn.orchestrator.state import State


@dataclass
class Reply:
    answer: str = ""                   # toast text for answerCallbackQuery
    alert: bool = False
    edit_text: str | None = None       # replace the message text (keyboard removed unless edit_buttons)
    edit_buttons: keyboards.Rows | None = None
    buttons_only: bool = False         # only update the keyboard


def authorized(settings, user_id: int) -> bool:
    return user_id in settings.allowed_user_ids


def handle_callback(conn, settings, user_id: int, data: str) -> Reply:
    if not authorized(settings, user_id):
        return Reply("Not authorised.", alert=True)
    parts = data.split(":")
    kind = parts[0]
    try:
        run_id = int(parts[1])
    except (IndexError, ValueError):
        return Reply("Malformed button.")
    run = repo.get_run(conn, run_id)
    if run is None:
        return Reply("Unknown run.")

    if kind == "t":
        try:
            selected = repo.toggle_selection(conn, run_id, parts[2])
        except PermissionError:
            return Reply("Selection is closed.", alert=True)
        except (KeyError, IndexError):
            return Reply("Unknown story.")
        return Reply(edit_buttons=keyboards.selection_keyboard(run_id, repo.proposals(conn, run_id), selected),
                     buttons_only=True)

    if kind == "c":
        slots = repo.selected_slots(conn, run_id)
        problem = repo.validate_selection(slots)
        if problem:
            return Reply(problem, alert=True)
        if not repo.set_state(conn, run_id, State.SELECTED, expected=State.AWAITING_SELECTION):
            return Reply("Already confirmed.")
        props = {p["slot"]: p for p in repo.proposals(conn, run_id)}
        summary = "\n".join(f"{i}. {s} \u00b7 {texts._e(props[s]['title'])}" for i, s in enumerate(slots, 1))
        return Reply("Confirmed.", edit_text=f"<b>WWNN {run['iso_week']} \u2014 selection locked</b>\n{summary}\n\n"
                                             "Writing the script now. Voices follow for your approval.")

    if kind == "s":
        if repo.set_state(conn, run_id, State.SKIPPED, expected=State.AWAITING_SELECTION):
            return Reply("Skipped.", edit_text=f"WWNN {run['iso_week']}: skipped this week.")
        return Reply("Too late to skip.")

    if kind in {"a", "g", "x"}:
        try:
            version = int(parts[2])
        except (IndexError, ValueError):
            return Reply("Malformed button.")
        if run["state"] != State.AWAITING_APPROVAL.value or run["script_version"] != version:
            return Reply("This version is no longer awaiting approval.", alert=True)
        if kind == "a":
            repo.approve_script(conn, run_id, version)
            repo.set_state(conn, run_id, State.APPROVED, expected=State.AWAITING_APPROVAL)
            return Reply("Approved.", edit_text=f"\u2705 WWNN {run['iso_week']} script v{version} approved. "
                                                "LongCat rendering starts now; progress updates follow.")
        if kind == "g":
            repo.update_context(conn, run_id, feedback="The producer asked for a fresh rewrite: new jokes, "
                                                       "different angles, same facts.", post_tts_feedback="")
            repo.set_state(conn, run_id, State.SELECTED, expected=State.AWAITING_APPROVAL, pacing_rounds=0)
            return Reply("Regenerating.", edit_text=f"\U0001F501 v{version} discarded, rewriting.")
        repo.set_state(conn, run_id, State.CANCELLED, expected=State.AWAITING_APPROVAL)
        return Reply("Rejected.", edit_text=f"\u274c WWNN {run['iso_week']} cancelled at script v{version}.")

    if kind == "rs":
        if run["state"] != State.FAILED.value:
            return Reply("Run is not failed.")
        target = run["failed_stage"] or State.SELECTED.value
        repo.set_state(conn, run_id, target, expected=State.FAILED, error=None)
        return Reply("Resuming.", edit_text=f"\u25b6 Resuming WWNN {run['iso_week']} at {target}.")

    return Reply("Unknown action.")


def status_text(conn) -> str:
    rows = conn.execute("SELECT * FROM weekly_runs ORDER BY id DESC LIMIT 5").fetchall()
    if not rows:
        return "No runs yet."
    return "\n".join(f"#{r['id']} {r['iso_week']}: {r['state']}"
                     + (f" (failed in {r['failed_stage']})" if r["failed_stage"] and r["state"] == "FAILED" else "")
                     for r in rows)
