"""End-to-end dry run through BOTH Telegram gates with mocks for Ollama/Chatterbox/LongCat/YouTube.
Produces real (small) Video A and Short MP4s with ffmpeg. ~1 minute on a laptop CPU."""

import json
import subprocess
from pathlib import Path

import pytest

from conftest import needs_ffmpeg
from wwnn.bot import handlers
from wwnn.bot.notify import OutboxNotifier
from wwnn.compose.assets import make_placeholders
from wwnn.config import Settings
from wwnn.db import repo, seed
from wwnn.db.migrate import open_db
from wwnn.orchestrator.stages import Orchestrator
from wwnn.orchestrator.state import State

FAST = dict(video_a_width=640, video_a_height=360, short_width=360, short_height=640, x264_preset="ultrafast",
            x264_crf=28, video_a_min_s=50, video_a_max_s=120, annika_max_speech_s=30, longcat_max_shot_s=20)


def _probe(p):
    out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(p)],
                         capture_output=True, text=True, check=True).stdout
    d = json.loads(out)
    v = next(s for s in d["streams"] if s["codec_type"] == "video")
    return v["width"], v["height"], float(d["format"]["duration"]), {s["codec_type"] for s in d["streams"]}


def _outbox(settings):
    path = settings.data_dir / "telegram_outbox.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


@pytest.mark.slow
@needs_ffmpeg
def test_full_pipeline_with_human_gates(tmp_path: Path):
    s = Settings.from_env(env_file=Path("/nonexistent/.env"), dry_run=True, auto_approve=False,
                          data_dir=tmp_path / "data", db_path=tmp_path / "data" / "wwnn.db",
                          assets_dir=tmp_path / "assets", stage_runner="local",
                          telegram_allowed_user_ids="111", **FAST)
    make_placeholders(s)
    conn = open_db(s.db_path)
    seed.seed_samples(conn)
    orch = Orchestrator(s, conn, OutboxNotifier(s.data_dir / "telegram_outbox.jsonl"))

    # Sunday push: 5 new + 3 archive with checkbox keyboard, then wait
    run_id = orch.start_week("2099-W09")
    assert repo.get_run(conn, run_id)["state"] == State.AWAITING_SELECTION.value
    props = repo.proposals(conn, run_id)
    assert sum(p["kind"] == "live" for p in props) == 5 and sum(p["kind"] == "archive" for p in props) == 3
    msgs = _outbox(s)
    assert any(cb.startswith("t:") for row in msgs[-1]["buttons"] for _, cb in row)
    assert orch.advance(run_id) == State.AWAITING_SELECTION.value      # nothing happens without the user

    for slot in ("N1", "N2", "N3", "N4", "A1", "A2"):
        handlers.handle_callback(conn, s, 111, f"t:{run_id}:{slot}")
    handlers.handle_callback(conn, s, 111, f"c:{run_id}")

    # script + voices -> approval gate; LongCat must NOT have run yet
    assert orch.advance(run_id, max_steps=40) == State.AWAITING_APPROVAL.value
    run_dir = Path(next(s.runs_dir.iterdir()))
    assert not (run_dir / "avatar" / "tom.mp4").exists()
    kinds = [m["kind"] for m in _outbox(s)]
    assert kinds.count("audio") == 2 and "document" in kinds
    approval = _outbox(s)[-1]
    version = repo.get_run(conn, run_id)["script_version"]
    assert [cb for row in approval["buttons"] for _, cb in row] == [f"a:{run_id}:{version}", f"g:{run_id}:{version}",
                                                                   f"x:{run_id}:{version}"]
    doc = json.loads(repo.latest_script(conn, run_id)["json"])
    assert doc["segments"][-1]["anchor"] == "annika"
    assert any(seg["kind"] == "handover" and "from the archive" in seg["text"].lower() for seg in doc["segments"])

    handlers.handle_callback(conn, s, 111, f"a:{run_id}:{version}")
    assert orch.advance(run_id, max_steps=40) == State.DONE.value, repo.get_run(conn, run_id)["error"]

    a, b = repo.get_episode(conn, run_id, "A"), repo.get_episode(conn, run_id, "B")
    wa, ha, da, sa = _probe(a["path"])
    wb, hb, db, sb = _probe(b["path"])
    assert (wa, ha) == (640, 360) and (wb, hb) == (360, 640)
    assert db < 60 and da > db and sa == sb == {"video", "audio"}
    ups = conn.execute("SELECT privacy_sent, privacy_verified, status FROM uploads").fetchall()
    assert len(ups) == 2 and all(tuple(u) == ("private", "private", "done") for u in ups)
    final = _outbox(s)[-1]["text"]
    assert "PRIVATE" in final and "related video" in final.lower()
