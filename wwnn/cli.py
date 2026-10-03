"""``wwnn`` command line (also ``python -m wwnn``)."""

from __future__ import annotations

import argparse
import sys
import tempfile
import time
from pathlib import Path

from loguru import logger

from wwnn.config import Settings


def _settings(args) -> Settings:
    over = {}
    if getattr(args, "dry_run", False):
        over["dry_run"] = True
    return Settings.from_env(**over)


def _conn(settings: Settings):
    from wwnn.db.migrate import open_db
    return open_db(settings.db_path)


def _orch(settings: Settings):
    from wwnn.bot.notify import make_notifier
    from wwnn.orchestrator.stages import Orchestrator
    return Orchestrator(settings, _conn(settings), make_notifier(settings))


def cmd_dry_run(args) -> int:
    """Full pipeline with mocks (no Ollama/Chatterbox/LongCat/YouTube/Telegram), auto-approved gates."""
    out = Path(args.out or tempfile.mkdtemp(prefix="wwnn-dryrun-")).resolve()
    over = dict(dry_run=True, auto_approve=True, data_dir=out / "data", db_path=out / "data" / "wwnn.db",
                assets_dir=out / "assets", stage_runner="local")
    if args.fast:
        over.update(video_a_width=640, video_a_height=360, short_width=360, short_height=640,
                    x264_preset="ultrafast", x264_crf=28, video_a_min_s=50, video_a_max_s=120,
                    annika_max_speech_s=30, longcat_max_shot_s=20)
    else:
        over.update(x264_preset="veryfast")
    settings = Settings.from_env(**over)
    from wwnn.compose.assets import make_placeholders
    from wwnn.db import repo, seed

    make_placeholders(settings)
    orch = _orch(settings)
    seed.seed_samples(orch.conn)
    t0 = time.time()
    run_id = orch.start_week("2099-W01")
    state = orch.advance(run_id, max_steps=40)
    run = repo.get_run(orch.conn, run_id)
    print(f"\nDry run finished in {time.time() - t0:.0f}s: state={state}")
    if state != "DONE":
        print(f"error: {run['error']}", file=sys.stderr)
        return 1
    for v in ("A", "B"):
        ep = repo.get_episode(orch.conn, run_id, v)
        print(f"Video {v}: {ep['path']}  ({ep['duration_s']:.1f}s, {ep['width']}x{ep['height']})")
    print(f"Telegram outbox: {settings.data_dir / 'telegram_outbox.jsonl'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="wwnn", description="WWNN weekly pipeline")
    sub = ap.add_subparsers(dest="cmd", required=True)

    db = sub.add_parser("db", help="database").add_subparsers(dest="db_cmd", required=True)
    db.add_parser("migrate")
    db.add_parser("seed", help="load the SAMPLE archive items")
    imp = sub.add_parser("archive", help="archive items").add_subparsers(dest="a_cmd", required=True)
    p = imp.add_parser("import")
    p.add_argument("file")

    a = sub.add_parser("assets").add_subparsers(dest="as_cmd", required=True)
    p = a.add_parser("placeholders", help="write dummy placeholder assets")
    p.add_argument("--force", action="store_true")
    a.add_parser("check", help="list placeholder assets still in use")

    sub.add_parser("ingest", help="scrape + screen new stories")
    p = sub.add_parser("week", help="start this week's run (Sunday timer)")
    p.add_argument("--week", help="ISO week, e.g. 2026-W41 (default: current)")
    p.add_argument("--dry-run", action="store_true")
    sub.add_parser("tick", help="advance all runs once")
    p = sub.add_parser("loop", help="orchestrator service loop")
    p.add_argument("--interval", type=float, default=30.0)
    p = sub.add_parser("resume")
    p.add_argument("run_id", type=int)
    sub.add_parser("status")
    sub.add_parser("bot", help="run the Telegram bot")
    y = sub.add_parser("youtube").add_subparsers(dest="y_cmd", required=True)
    p = y.add_parser("auth", help="one-time OAuth consent")
    p.add_argument("--port", type=int, default=8765)
    lc = sub.add_parser("longcat").add_subparsers(dest="l_cmd", required=True)
    p = lc.add_parser("patch", help="write the patched LongCat entry script")
    p.add_argument("repo_dir")
    p = sub.add_parser("dry-run", help="end-to-end run with mocks; produces real MP4s")
    p.add_argument("--out")
    p.add_argument("--fast", action="store_true", help="small resolution + short durations")

    args = ap.parse_args(argv)
    if args.cmd == "dry-run":
        return cmd_dry_run(args)
    settings = _settings(args)

    if args.cmd == "db":
        conn = _conn(settings)
        if args.db_cmd == "seed":
            from wwnn.db.seed import seed_samples
            seed_samples(conn)
        print(f"database ready: {settings.db_path}")
    elif args.cmd == "archive":
        from wwnn.db.seed import import_file
        print(f"imported {import_file(_conn(settings), args.file)} items")
    elif args.cmd == "assets":
        from wwnn.compose.assets import make_placeholders, placeholders_in_use
        if args.as_cmd == "placeholders":
            for pth in make_placeholders(settings, force=args.force):
                print(pth)
        else:
            used = placeholders_in_use(settings)
            print("\n".join(used) if used else "no placeholder assets in use")
            return 1 if used else 0
    elif args.cmd == "ingest":
        from wwnn.ingest.pipeline import ingest
        print(ingest(_conn(settings), settings))
    elif args.cmd == "week":
        print(f"run #{_orch(settings).start_week(args.week)}")
    elif args.cmd == "tick":
        _orch(settings).tick()
    elif args.cmd == "loop":
        _orch(settings).loop(args.interval)
    elif args.cmd == "resume":
        print(_orch(settings).resume(args.run_id))
    elif args.cmd == "status":
        from wwnn.bot.handlers import status_text
        print(status_text(_conn(settings)))
    elif args.cmd == "bot":
        from wwnn.bot.app import main as bot_main
        bot_main()
    elif args.cmd == "youtube":
        from wwnn.upload.auth_bootstrap import bootstrap
        print(f"token written to {bootstrap(settings, args.port)}")
    elif args.cmd == "longcat":
        from wwnn.avatar.patch_longcat import patch_repo
        print(patch_repo(args.repo_dir))
    return 0


if __name__ == "__main__":
    logger.remove()
    logger.add(sys.stderr, level="INFO")
    sys.exit(main())
