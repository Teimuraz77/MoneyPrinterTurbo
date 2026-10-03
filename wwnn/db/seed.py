"""Seed the archive with sample items, or import your own vetted items from CSV/JSON."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from loguru import logger

from wwnn.db import repo
from wwnn.ingest.safety import keyword_check
from wwnn.util import utcnow

SAMPLE_FILE = Path(__file__).parent / "sample_archive.json"
REQUIRED = ("slug", "title", "summary", "source_citation")


def seed_samples(conn) -> int:
    data = json.loads(SAMPLE_FILE.read_text(encoding="utf-8"))
    n = 0
    for item in data["items"]:
        item = dict(item, is_sample=True, verified_by="SAMPLE - NOT VERIFIED", verified_at=utcnow())
        _import_one(conn, item)
        n += 1
    logger.warning(f"seeded {n} SAMPLE archive items (is_sample=1) - replace with vetted items before going live")
    return n


def _import_one(conn, item: dict) -> int:
    missing = [k for k in REQUIRED if not item.get(k)]
    if missing:
        raise ValueError(f"archive item {item.get('slug')!r} missing {missing}")
    verdict = keyword_check(f"{item['title']} {item['summary']}")
    if not verdict.safe:
        raise ValueError(f"archive item {item['slug']!r} violates the taboo filter: {verdict.reason}")
    item.setdefault("verified_by", "unknown")
    item.setdefault("verified_at", utcnow())
    if item.get("absurdity") not in (None, ""):
        item["absurdity"] = int(item["absurdity"])
    return repo.upsert_archive_item(conn, item)


def import_file(conn, path: str | Path) -> int:
    """Import vetted archive items. CSV columns: slug,title,summary,event_date,place,
    source_citation,source_url,rights_note,tags (semicolon separated),absurdity,verified_by."""
    path = Path(path)
    if path.suffix.lower() == ".json":
        items = json.loads(path.read_text(encoding="utf-8"))
        items = items.get("items", items) if isinstance(items, dict) else items
    else:
        with path.open(newline="", encoding="utf-8") as f:
            items = list(csv.DictReader(f))
        for it in items:
            if isinstance(it.get("tags"), str):
                it["tags"] = [t.strip() for t in it["tags"].split(";") if t.strip()]
    for it in items:
        _import_one(conn, dict(it))
    return len(items)
