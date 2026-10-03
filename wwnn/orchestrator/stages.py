"""Orchestrator: advances weekly runs through the state machine, one checkpointed stage at a time.

Runs on the host (systemd ``wwnn-orchestrator.service`` -> ``wwnn loop``). GPU stages run either
in-process (``WWNN_STAGE_RUNNER=local``) or in their own containers via ``docker compose run``
(``WWNN_STAGE_RUNNER=docker``), which keeps Chatterbox's and LongCat's conflicting dependency
pins apart and frees VRAM when each job exits.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
import time
import traceback
from pathlib import Path
from zoneinfo import ZoneInfo

from loguru import logger

from wwnn.bot import keyboards, texts
from wwnn.config import Settings
from wwnn.db import repo
from wwnn.ingest import pipeline
from wwnn.llm.ollama import OllamaClient
from wwnn.orchestrator.gpu import gpu_stage
from wwnn.orchestrator.state import GATES, TERMINAL, State
from wwnn.script import pacing, writer
from wwnn.script.mock import MockBackend
from wwnn.util import StageError, duration, ffmpeg, iso_week, read_json, sha256_file, utcnow, write_json

DOCKER_SERVICES = {"tts": ("tts", "wwnn.tts.synth"), "avatar": ("longcat", "wwnn.avatar.runner"),
                   "compose": ("compose", "wwnn.compose.cli")}


class Orchestrator:
    def __init__(self, settings: Settings, conn, notifier):
        self.s = settings
        self.conn = conn
        self.notify = notifier
        self.ollama = OllamaClient(settings.ollama_base_url, settings.ollama_model, settings.ollama_timeout_s,
                                   settings.ollama_temperature)

    # ------------------------------------------------------------------ helpers
    def run_dir(self, run) -> Path:
        d = self.s.runs_dir / f"{run['iso_week']}-r{run['id']}"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _local_time(self, iso: str) -> str:
        t = dt.datetime.fromisoformat(iso).astimezone(ZoneInfo(self.s.timezone))
        return t.strftime("%a %d %b %H:%M ") + t.tzname()

    def _bumper_seconds(self) -> tuple[float, float]:
        total = 0.0
        for p, fallback in ((self.s.bumper_intro, 4.0), (self.s.bumper_transition, 3.0), (self.s.bumper_outro, 4.0)):
            path = self.s.path(p)
            total += duration(path) if path.exists() else fallback
        short_intro = duration(self.s.path(self.s.short_intro)) if self.s.short_intro and \
            self.s.path(self.s.short_intro).exists() else 0.0
        return total, short_intro

    def _backend(self, run):
        if self.s.dry_run or run["dry_run"]:
            return MockBackend(self.s)
        if not self.ollama.available():
            raise StageError(f"Ollama is not reachable at {self.s.ollama_base_url}")
        return writer.LLMBackend(self.ollama, self.s)

    def _stage(self, name: str, run_dir: Path, inprocess) -> None:
        if self.s.stage_runner == "docker" and name in DOCKER_SERVICES:
            service, module = DOCKER_SERVICES[name]
            cmd = ["docker", "compose", "-f", str(self.s.compose_file), "run", "--rm", "-T", service,
                   "python", "-m", module, "--run-dir", str(run_dir)]
            logger.info("$ " + " ".join(cmd))
            log = run_dir / f"{name}.docker.log"
            with open(log, "w") as fh:
                rc = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT).returncode
            if rc != 0:
                raise StageError(f"{name} container exited {rc}:\n" + log.read_text(errors="replace")[-1500:])
        else:
            inprocess()

    # ------------------------------------------------------------------ week start
    def start_week(self, week: str | None = None, dry_run: bool | None = None) -> int:
        week = week or iso_week()
        existing = repo.active_run_for_week(self.conn, week)
        if existing:
            logger.info(f"run #{existing['id']} already exists for {week} ({existing['state']})")
            return existing["id"]
        run_id = repo.create_run(self.conn, week, self.s.dry_run if dry_run is None else dry_run)
        self.advance(run_id)
        return run_id

    # ------------------------------------------------------------------ main loop
    def tick(self) -> None:
        active = [r for r in self.conn.execute("SELECT * FROM weekly_runs ORDER BY id").fetchall()
                  if State(r["state"]) not in TERMINAL and r["state"] != State.FAILED.value]
        for run in active:
            self.advance(run["id"])

    def loop(self, interval: float = 30.0) -> None:
        logger.info("orchestrator loop started")
        while True:
            try:
                self.tick()
            except Exception as e:   # the loop itself must never die
                logger.exception(f"tick failed: {e}")
            time.sleep(interval)

    def advance(self, run_id: int, max_steps: int = 20) -> str:
        """Run consecutive non-gate stages until a gate, a terminal state or a failure."""
        for _ in range(max_steps):
            run = repo.get_run(self.conn, run_id)
            state = State(run["state"])
            if state in TERMINAL or state == State.FAILED:
                return state.value
            if state in GATES:
                if not self._gate(run, state):
                    return state.value
                continue
            handler = getattr(self, f"_on_{state.value.lower()}")
            try:
                handler(run)
            except Exception as e:
                self.fail(run, state, e)
                return State.FAILED.value
        return repo.get_run(self.conn, run_id)["state"]

    def fail(self, run, state: State, exc: Exception) -> None:
        tb = traceback.format_exc()
        logger.error(f"run #{run['id']} failed in {state.value}: {exc}\n{tb}")
        resume_to = getattr(exc, "resume_state", None) or state.value
        repo.set_state(self.conn, run["id"], State.FAILED, failed_stage=resume_to, error=str(exc)[:4000])
        repo.add_event(self.conn, run["id"], "error", state.value, str(exc)[:2000])
        self.notify.send_message(texts.failure_text(dict(run), state.value, f"{exc}"),
                                 keyboards.resume_keyboard(run["id"]))

    def resume(self, run_id: int) -> str:
        run = repo.get_run(self.conn, run_id)
        if run["state"] != State.FAILED.value:
            raise RuntimeError(f"run #{run_id} is {run['state']}, not FAILED")
        repo.set_state(self.conn, run_id, run["failed_stage"] or State.SELECTED.value, error=None)
        return self.advance(run_id)

    # ------------------------------------------------------------------ gates
    def _gate(self, run, state: State) -> bool:
        """Return True if the gate was resolved automatically (dry-run auto-approve or deadline)."""
        now = dt.datetime.now(dt.timezone.utc)
        if state == State.AWAITING_SELECTION:
            if self.s.auto_approve:
                props = repo.proposals(self.conn, run["id"])
                live = [p["slot"] for p in props if p["kind"] == "live"][:4]
                arch = [p["slot"] for p in props if p["kind"] == "archive"][:3]
                repo.set_selection(self.conn, run["id"], live + arch)
                return repo.set_state(self.conn, run["id"], State.SELECTED, expected=state)
            deadline = dt.datetime.fromisoformat(run["selection_deadline"]) if run["selection_deadline"] else None
            if deadline and now > deadline:
                repo.set_state(self.conn, run["id"], State.SKIPPED, expected=state)
                self.notify.send_message(f"WWNN {run['iso_week']}: no selection before the deadline, week skipped.")
                return False
            if deadline and not run["reminded_at"] and now > deadline - dt.timedelta(hours=6):
                repo.update_run(self.conn, run["id"], reminded_at=utcnow())
                self.notify.send_message(f"\u23f0 WWNN {run['iso_week']}: story selection closes at "
                                         f"{self._local_time(run['selection_deadline'])}.")
            return False
        if state == State.AWAITING_APPROVAL:
            if self.s.auto_approve:
                repo.approve_script(self.conn, run["id"], run["script_version"])
                return repo.set_state(self.conn, run["id"], State.APPROVED, expected=state)
            since = dt.datetime.fromisoformat(run["updated_at"])
            if not run["reminded_at"] and now - since > dt.timedelta(hours=self.s.approval_reminder_hours):
                repo.update_run(self.conn, run["id"], reminded_at=utcnow())
                self.notify.send_message(f"\u23f0 WWNN {run['iso_week']}: script v{run['script_version']} "
                                         "is still waiting for your approval (buttons above).")
        return False

    # ------------------------------------------------------------------ stages
    def _on_created(self, run) -> None:
        pipeline.ingest(self.conn, self.s)
        props = pipeline.propose(self.conn, self.s, run["id"])
        deadline = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=self.s.selection_deadline_hours)
                    ).replace(microsecond=0).isoformat()
        repo.set_state(self.conn, run["id"], State.AWAITING_SELECTION, selection_deadline=deadline)
        run = repo.get_run(self.conn, run["id"])
        warn = self._placeholder_warning()
        msg_id = self.notify.send_message(
            texts.selection_text(dict(run), props, self._local_time(deadline)) + (f"\n\n{warn}" if warn else ""),
            keyboards.selection_keyboard(run["id"], props, []))
        repo.update_run(self.conn, run["id"], telegram_message_id=msg_id)

    def _placeholder_warning(self) -> str:
        if self.s.dry_run:
            return ""
        from wwnn.compose.assets import placeholders_in_use
        used = placeholders_in_use(self.s)
        return ("\u26a0 Still using DUMMY placeholder assets: " + ", ".join(Path(p).name for p in used)) if used else ""

    def _on_selected(self, run) -> None:
        """Write (or rewrite) the script with the dynamic pacing loop."""
        sel = repo.selected_items(self.conn, run["id"])
        live, archive = sel["live"], sel["archive"]
        for a in archive:
            a["event_date"] = a.get("event_date")
        ctx = repo.run_context(self.conn, run["id"])
        bumpers_s, short_intro_s = self._bumper_seconds()
        backend = self._backend(run)
        feedback = "\n".join(x for x in (ctx.get("feedback", ""), ctx.get("post_tts_feedback", "")) if x)
        result = writer.write_episode(backend, self.s, live, archive, bumpers_s=bumpers_s,
                                      short_intro_s=short_intro_s, wpm=ctx.get("wpm"),
                                      feedback=("\n" + feedback) if feedback else "")
        version = run["script_version"] + 1
        result.doc["version"] = version
        repo.save_script(self.conn, run["id"], version, result.model, writer.prompt_hash(), result.doc,
                         result.est["total_s"], result.warnings)
        rd = self.run_dir(run)
        write_json(rd / "script" / f"script_v{version}.json", {"doc": result.doc, "est": result.est,
                                                               "warnings": result.warnings})
        repo.clear_checkpoints(self.conn, run["id"], ["tts"])
        repo.set_state(self.conn, run["id"], State.SCRIPTED, script_version=version)

    def _doc(self, run) -> tuple[dict, dict]:
        row = repo.latest_script(self.conn, run["id"])
        return json.loads(row["json"]), dict(row)

    def _on_scripted(self, run) -> None:
        """TTS, then the post-TTS pacing check with REAL durations (cheap: LongCat hasn't run)."""
        from wwnn.tts.synth import MockEngine, build_job, run_tts

        doc, row = self._doc(run)
        rd = self.run_dir(run)
        job = build_job(doc, self.s)
        write_json(rd / "tts" / "job.json", job)
        mock = self.s.dry_run or bool(run["dry_run"])

        def inprocess():
            if mock:
                engine = MockEngine({"tom": self.s.wpm_tom, "annika": self.s.wpm_annika})
            else:
                from wwnn.tts.synth import ChatterboxEngine
                engine = ChatterboxEngine(self.s.chatterbox_model, self.s.tts_device)
            run_tts(rd, engine, job)

        if mock:
            inprocess()
        else:
            with gpu_stage("tts", self.s.data_dir / "gpu.lock", self.ollama):
                self._stage("tts", rd, inprocess)
        manifest = read_json(rd / "tts" / "manifest.json")
        tom_s, ann_s = manifest["tracks"]["tom"]["duration"], manifest["tracks"]["annika"]["duration"]
        bumpers_s, short_intro_s = self._bumper_seconds()
        budget = pacing.Budget.from_settings(self.s, bumpers_s, short_intro_s)
        problems = pacing.check(self.s, budget, tom_s, ann_s)
        real_total = budget.total(tom_s, ann_s)
        repo.set_script_real_seconds(self.conn, row["id"], real_total)
        if problems:
            wpm = {a: manifest["tracks"][a]["wpm"] for a in ("tom", "annika") if manifest["tracks"][a]["wpm"]}
            if run["pacing_rounds"] < self.s.post_tts_max_rounds:
                logger.warning(f"post-TTS pacing: {problems} -> re-scripting with calibrated wpm {wpm}")
                repo.update_context(self.conn, run["id"], wpm=wpm, post_tts_feedback=(
                    "The previous draft, read aloud, had these timing problems: " + "; ".join(problems) +
                    ". Adjust the length accordingly."))
                repo.set_state(self.conn, run["id"], State.SELECTED, pacing_rounds=run["pacing_rounds"] + 1)
                return
            if ann_s > budget.annika_cap_s:
                err = StageError(f"Annika's segment is {ann_s:.1f}s after {run['pacing_rounds']} rewrites; the Short "
                                 f"must stay under 60 s (cap {budget.annika_cap_s:.0f}s). Resume to rewrite.")
                err.resume_state = State.SELECTED.value
                raise err
        repo.update_context(self.conn, run["id"], approval_warnings=problems)
        repo.save_checkpoint(self.conn, run["id"], "tts", sha256_file(rd / "tts" / "job.json"),
                             {"tom": tom_s, "annika": ann_s})
        repo.set_state(self.conn, run["id"], State.VOICED)

    def _on_voiced(self, run) -> None:
        doc, row = self._doc(run)
        rd = self.run_dir(run)
        manifest = read_json(rd / "tts" / "manifest.json")
        tom_s, ann_s = manifest["tracks"]["tom"]["duration"], manifest["tracks"]["annika"]["duration"]
        bumpers_s, short_intro_s = self._bumper_seconds()
        real = {"tom": tom_s, "annika": ann_s, "total": bumpers_s + tom_s + ann_s,
                "short": short_intro_s + ann_s + self.s.cta_seconds}
        ctx = repo.run_context(self.conn, run["id"])
        warnings = list(json.loads(row["lint_warnings"] or "[]")) + list(ctx.get("approval_warnings") or [])
        if any(s.get("is_sample") for s in doc.get("sources", [])):
            warnings.append("Uses SAMPLE archive data - verify the facts before publishing.")
        pw = self._placeholder_warning()
        if pw:
            warnings.append(pw)
        md = rd / "script" / f"WWNN_{run['iso_week']}_script_v{run['script_version']}.md"
        md.write_text(script_markdown(doc, real), encoding="utf-8")
        self.notify.send_document(md, caption=f"Script v{run['script_version']}")
        for anchor, label in (("tom", "Tom Blunt - breaking news"), ("annika", "Annika - From the Archive (= Short)")):
            mp3 = rd / "tts" / f"{anchor}_preview.mp3"
            ffmpeg(["-i", rd / "tts" / manifest["tracks"][anchor]["wav"], "-c:a", "libmp3lame", "-b:a", "128k", mp3])
            self.notify.send_audio(mp3, caption=label)
        self.notify.send_message(texts.approval_text(dict(run), run["script_version"], {}, real, warnings),
                                 keyboards.approval_keyboard(run["id"], run["script_version"]))
        repo.set_state(self.conn, run["id"], State.AWAITING_APPROVAL, reminded_at=None)

    def _on_approved(self, run) -> None:
        from wwnn.avatar.runner import run_avatar

        rd = self.run_dir(run)
        mock = self.s.dry_run or bool(run["dry_run"])
        last = {"t": 0.0}

        def progress(i, n, eta):
            if time.time() - last["t"] > 600 or i == n:
                last["t"] = time.time()
                self.notify.send_message(f"\U0001F3AC WWNN {run['iso_week']}: shot {i}/{n} rendered, "
                                         f"ETA {texts.fmt_s(eta)} (m:ss)" if eta < 3600 else
                                         f"\U0001F3AC WWNN {run['iso_week']}: shot {i}/{n} rendered, "
                                         f"ETA {eta / 3600:.1f} h")

        def inprocess():
            run_avatar(rd, self.s, mock=mock, on_progress=progress, conn=self.conn, run_id=run["id"])

        if mock:
            inprocess()
        else:
            self.notify.send_message(f"\U0001F3AC WWNN {run['iso_week']}: LongCat rendering started.")
            with gpu_stage("longcat", self.s.data_dir / "gpu.lock", self.ollama):
                self._stage("avatar", rd, inprocess)
        repo.save_checkpoint(self.conn, run["id"], "avatar", "", read_json(rd / "avatar" / "manifest.json"))
        repo.set_state(self.conn, run["id"], State.RENDERED)

    def _on_rendered(self, run) -> None:
        from wwnn.compose.timeline import compose_all

        doc, _ = self._doc(run)
        rd = self.run_dir(run)
        write_json(rd / "script" / "approved.json", doc)
        self._stage("compose", rd, lambda: compose_all(rd, self.s, doc))
        m = read_json(rd / "compose" / "manifest.json")
        from wwnn.upload.metadata import video_a_meta
        meta_a = video_a_meta(doc, self.s)
        for video, key in (("A", "A"), ("B", "B")):
            v = m[key]
            repo.save_episode(self.conn, run["id"], video, path=v["path"], sha256=v["sha256"], duration_s=v["duration"],
                              width=v["width"], height=v["height"],
                              title=meta_a.title if video == "A" else doc.get("short_title"))
        repo.update_context(self.conn, run["id"], qc=m.get("qc", []))
        repo.set_state(self.conn, run["id"], State.COMPOSED)

    def _youtube(self, run):
        from wwnn.upload import youtube
        if self.s.dry_run or run["dry_run"]:
            return youtube.FakeYouTube()
        return youtube.client(self.s)

    def _on_composed(self, run) -> None:
        from wwnn.upload import youtube
        from wwnn.upload.metadata import video_a_meta, video_b_meta

        if not self.s.upload_enabled:
            repo.update_context(self.conn, run["id"], upload_skipped=True)
            repo.set_state(self.conn, run["id"], State.UPLOADED)
            return
        doc, _ = self._doc(run)
        yt = self._youtube(run)
        media = (lambda p: None) if isinstance(yt, youtube.FakeYouTube) else None
        ids = {}
        for video in ("A", "B"):            # A first: its URL goes into B's description
            done = repo.done_upload_for(self.conn, run["id"], video)
            if done:
                ids[video] = done["youtube_id"]
                continue
            ep = repo.get_episode(self.conn, run["id"], video)
            meta = video_a_meta(doc, self.s) if video == "A" else video_b_meta(doc, self.s, ids["A"])
            up_id = repo.create_upload(self.conn, ep["id"])
            try:
                res = youtube.upload(yt, ep["path"], meta, media_factory=media)
            except youtube.PrivacyViolation as e:
                repo.fail_upload(self.conn, up_id, str(e))
                self.notify.send_message(f"\U0001F6A8\U0001F6A8 PRIVACY CHECK FAILED: {e}")
                raise
            except Exception as e:
                repo.fail_upload(self.conn, up_id, str(e))
                raise
            repo.finish_upload(self.conn, up_id, res["id"], res["privacy_verified"])
            ids[video] = res["id"]
        repo.update_context(self.conn, run["id"], youtube_ids=ids)
        repo.set_state(self.conn, run["id"], State.UPLOADED)

    def _on_uploaded(self, run) -> None:
        ctx = repo.run_context(self.conn, run["id"])
        doc, _ = self._doc(run)
        if ctx.get("upload_skipped"):
            a, b = repo.get_episode(self.conn, run["id"], "A"), repo.get_episode(self.conn, run["id"], "B")
            self.notify.send_message(f"WWNN {run['iso_week']}: upload disabled. Files:\n{a['path']}\n{b['path']}")
        else:
            ids = ctx["youtube_ids"]
            self.notify.send_message(texts.review_text(dict(run), ids["A"], ids["B"], ctx.get("qc", []),
                                                       bool(self.s.dry_run or run["dry_run"])))
        props = {p["slot"]: p for p in repo.proposals(self.conn, run["id"])}
        repo.mark_items_used(self.conn, run["id"],
                             [props[s]["archive_id"] for s in doc["archive_slots"] if s in props],
                             [props[s]["live_id"] for s in doc["live_slots"] if s in props])
        repo.set_state(self.conn, run["id"], State.DONE)


def script_markdown(doc: dict, real: dict) -> str:
    lines = [f"# {doc.get('episode_title', 'WWNN')}", "",
             f"Tom {texts.fmt_s(real['tom'])} · Annika/Short {texts.fmt_s(real['annika'])} · "
             f"Video A ≈ {texts.fmt_s(real['total'])} · Short ≈ {texts.fmt_s(real['short'])}", ""]
    for s in doc["segments"]:
        lt = f" — LT: {s['lower_third_title']} / {s.get('lower_third_sub') or ''}" if s.get("lower_third_title") else ""
        lines += [f"## {s['anchor'].upper()} · {s['kind']}{(' · ' + s['item_slot']) if s.get('item_slot') else ''}{lt}",
                  "", s["text"], ""]
    lines += ["---", f"Short title: {doc.get('short_title')}", f"Short hook: {doc.get('short_hook')}", "",
              "Sources:"] + [f"- [{x['slot']}] {x['title']} {x.get('url') or ''}" for x in doc.get("sources", [])]
    return "\n".join(lines)
