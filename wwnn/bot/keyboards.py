"""Inline keyboards as plain data: rows of (label, callback_data). callback_data <= 64 bytes.

  t:<run>:<slot>   toggle a story            c:<run>   confirm selection   s:<run>  skip week
  a:<run>:<ver>    approve script+audio      g:<run>:<ver> regenerate    x:<run>:<ver> reject
  rs:<run>         resume a failed run
"""

from __future__ import annotations

Rows = list[list[tuple[str, str]]]


def selection_keyboard(run_id: int, proposals: list[dict], selected: list[str]) -> Rows:
    rows: Rows = []
    for p in proposals:
        mark = "\u2611" if p["slot"] in selected else "\u2610"
        prio = f" #{selected.index(p['slot']) + 1}" if p["slot"] in selected else ""
        rows.append([(f"{mark} {p['slot']}{prio} \u00b7 {p['title'][:38]}", f"t:{run_id}:{p['slot']}")])
    n_new = sum(1 for s in selected if s.startswith("N"))
    n_arc = sum(1 for s in selected if s.startswith("A"))
    rows.append([(f"\u2705 Confirm ({n_new} new \u00b7 {n_arc} archive)", f"c:{run_id}"),
                 ("\u23ed Skip this week", f"s:{run_id}")])
    return rows


def approval_keyboard(run_id: int, version: int) -> Rows:
    return [[("\u2705 Approve & render", f"a:{run_id}:{version}")],
            [("\U0001F501 Regenerate", f"g:{run_id}:{version}"), ("\u274c Reject", f"x:{run_id}:{version}")]]


def resume_keyboard(run_id: int) -> Rows:
    return [[("\u25b6 Resume", f"rs:{run_id}")]]


def to_bot_api(rows: Rows | None) -> dict | None:
    if not rows:
        return None
    return {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in row] for row in rows]}
