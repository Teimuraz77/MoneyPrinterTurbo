"""Ingest (scrape -> dedupe -> taboo screen -> store) and the weekly 5 + 3 proposal."""

from __future__ import annotations

from loguru import logger

from wwnn.config import Settings
from wwnn.db import repo
from wwnn.ingest import dedupe, safety
from wwnn.ingest.sources import RawItem, fetch_newsdata, fetch_rss
from wwnn.llm.ollama import OllamaClient

# Offline stand-ins used in dry-run mode. Invented, harmless, clearly labelled.
DRY_RUN_ITEMS = [
    RawItem("dryrun:sample", "https://example.invalid/goose-council",
            "Goose elected chair of parish council after nobody else attends",
            "A parish council meeting went ahead with a goose in the chair after the only other "
            "attendee left early. The minutes record no objections."),
    RawItem("dryrun:sample", "https://example.invalid/roundabout",
            "Town unveils roundabout with no roads leading to it",
            "Officials described the new roundabout as future-proof. Roads are expected in 2031."),
    RawItem("dryrun:sample2", "https://example.invalid/pumpkin",
            "Record pumpkin too large to fit through competition gate",
            "Organisers judged the giant pumpkin in the car park after it failed to fit through the gate."),
    RawItem("dryrun:sample2", "https://example.invalid/queue",
            "Hundreds queue for opening of shop that sells only left socks",
            "The owner said the business model was obvious to anyone who has ever done laundry."),
    RawItem("dryrun:sample3", "https://example.invalid/robot",
            "Robot lawnmower files for overtime, according to its own app",
            "A software update caused a robot lawnmower to send its owner weekly timesheets."),
    RawItem("dryrun:sample3", "https://example.invalid/llama",
            "Llama attends graduation ceremony and is mistakenly handed a diploma",
            "University staff said the llama had attended more lectures than some students."),
    RawItem("dryrun:sample", "https://example.invalid/excluded",
            "Man killed in motorway crash", "This item must be excluded by the taboo filter."),
]


def ingest(conn, settings: Settings, use_llm: bool | None = None) -> dict:
    raw: list[RawItem] = []
    if settings.dry_run:
        raw = list(DRY_RUN_ITEMS)
    else:
        for name, url in settings.feeds():
            raw += fetch_rss(name, url)
        for q in settings.newsdata_queries.split("|"):
            if q.strip():
                raw += fetch_newsdata(settings.newsdata_api_key, q.strip(), settings.newsdata_language)

    use_llm = (settings.ollama_use_classifier and not settings.dry_run) if use_llm is None else use_llm
    client = None
    if use_llm:
        client = OllamaClient(settings.ollama_base_url, settings.ollama_classifier_model or settings.ollama_model,
                              settings.ollama_timeout_s)
        if not client.available():
            logger.warning("ollama not reachable; falling back to keyword screen only")
            client = None

    existing = repo.live_title_hashes(conn)
    stats = {"fetched": len(raw), "new": 0, "duplicates": 0, "excluded": 0}
    for it in raw:
        th = dedupe.title_hash(it.title)
        if dedupe.is_near_duplicate(th, existing):
            stats["duplicates"] += 1
            continue
        item_id = repo.insert_live_item(conn, {
            "source": it.source, "url": it.url, "url_hash": dedupe.url_hash(it.url), "title_hash": th,
            "title": it.title, "description": it.description, "language": it.language,
            "published_at": it.published_at})
        if item_id is None:
            stats["duplicates"] += 1
            continue
        existing.append(th)
        try:
            verdict = safety.screen(it.title, it.description, client)
        except Exception as e:  # classifier failure must not admit an item
            verdict = safety.Verdict(False, f"classifier error: {e}")
        repo.set_live_safety(conn, item_id, verdict.safe, verdict.absurdity, verdict.reason)
        stats["new"] += 1
        stats["excluded"] += 0 if verdict.safe else 1
    logger.info(f"ingest: {stats}")
    return stats


def propose(conn, settings: Settings, run_id: int) -> list[dict]:
    live = repo.live_candidates(conn, settings.proposal_live_count)
    archive = repo.archive_candidates(conn, settings.proposal_archive_count, settings.archive_cooldown_weeks)
    if len(live) < 2:
        raise RuntimeError(f"only {len(live)} safe live stories available; run `wwnn ingest` first")
    if not archive:
        raise RuntimeError("archive is empty; run `wwnn db seed` or `wwnn archive import`")
    for i, row in enumerate(live, 1):
        repo.add_proposal(conn, run_id, f"N{i}", "live", row["id"])
    for i, row in enumerate(archive, 1):
        repo.add_proposal(conn, run_id, f"A{i}", "archive", row["id"])
    return repo.proposals(conn, run_id)
