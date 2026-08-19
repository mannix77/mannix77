#!/usr/bin/env python3
"""Extend data/sources.json with post metadata from the publication archive.

Why this exists
---------------
The source index in this repository was assembled from search results, because
the environment it was built in blocks outbound access to substack.com. It
therefore covers a subset of the series. Run this from a network-permitting
environment to index the rest.

What it collects, and what it deliberately does not
---------------------------------------------------
It records **metadata only**: title, canonical URL, publication date. It does
not download, store, or excerpt article bodies, and there is no code path here
that would. The graph cites the series; it does not reproduce it. Keep it that
way - the concept nodes are original abstractions written for this repository,
and that is what makes the whole thing distributable.

Usage
-----
    python3 tools/refresh_corpus.py --dry-run
    python3 tools/refresh_corpus.py --write
    python3 tools/refresh_corpus.py --write --limit 400

Afterwards, review the diff, attach ``themes`` to the posts you care about, wire
them into concept/test/trap ``sources`` lists, then re-run:

    PYTHONPATH=src python3 -m graphify validate && PYTHONPATH=src python3 -m graphify build
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "data" / "sources.json"

ARCHIVE_API = "https://rogerlmartin.substack.com/api/v1/archive"
PAGE_SIZE = 50
USER_AGENT = "graphify-corpus-indexer/0.1 (metadata only; see tools/refresh_corpus.py)"

# fields we are willing to carry from the API response
KEEP = ("title", "canonical_url", "post_date", "slug")


def _slug_to_id(slug: str) -> str:
    stem = re.sub(r"[^a-z0-9]+", "_", slug.lower()).strip("_")
    stem = re.sub(r"_[0-9a-f]{8,}$", "", stem)  # trailing hash substack appends
    stem = re.sub(r"^\d{4}_\d{2}_\d{2}_", "", stem)  # leading date
    return f"src:{stem[:60].strip('_') or 'post'}"


def fetch_page(offset: int, timeout: float = 30.0) -> list[dict[str, Any]]:
    url = f"{ARCHIVE_API}?sort=new&limit={PAGE_SIZE}&offset={offset}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"unexpected archive response shape: {type(payload).__name__}")
    return [{k: post.get(k) for k in KEEP} for post in payload]


def fetch_all(limit: int) -> list[dict[str, Any]]:
    posts: list[dict[str, Any]] = []
    offset = 0
    while len(posts) < limit:
        try:
            page = fetch_page(offset)
        except urllib.error.URLError as exc:
            if not posts:
                raise SystemExit(
                    f"could not reach the archive ({exc}).\n"
                    "If this is a sandboxed environment, outbound access to substack.com is "
                    "probably blocked - run this from somewhere with network access."
                ) from None
            print(f"stopping early at offset {offset}: {exc}", file=sys.stderr)
            break
        if not page:
            break
        posts.extend(page)
        offset += PAGE_SIZE
    return posts[:limit]


def to_source_node(post: dict[str, Any]) -> dict[str, Any] | None:
    url = post.get("canonical_url")
    title = (post.get("title") or "").strip()
    if not url or not title:
        return None
    slug = post.get("slug") or url.rstrip("/").rsplit("/", 1)[-1]
    return {
        "id": _slug_to_id(slug),
        "type": "source",
        "label": title,
        "url": url,
        "kind": "post",
        "published": (post.get("post_date") or "")[:10],
        "themes": [],
        "full_text_ingested": False,
        "verified": "archive_api",
        "verified_on": None,  # stamped at write time
    }


def merge(existing: list[dict[str, Any]], fetched: list[dict[str, Any]], today: str) -> tuple[list[dict[str, Any]], int]:
    by_url = {node.get("url"): node for node in existing}
    by_id = {node["id"]: node for node in existing}
    added = 0

    for post in fetched:
        node = to_source_node(post)
        if node is None:
            continue
        node["verified_on"] = today

        current = by_url.get(node["url"])
        if current is not None:
            # keep hand-written fields; only fill in what is missing
            for key in ("published", "label"):
                if not current.get(key) and node.get(key):
                    current[key] = node[key]
            continue

        node_id = node["id"]
        suffix = 2
        while node_id in by_id:
            node_id = f"{node['id']}_{suffix}"
            suffix += 1
        node["id"] = node_id

        existing.append(node)
        by_id[node_id] = node
        by_url[node["url"]] = node
        added += 1

    return existing, added


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--write", action="store_true", help="write data/sources.json in place")
    parser.add_argument("--dry-run", action="store_true", help="report what would change and exit")
    parser.add_argument("--limit", type=int, default=400, help="maximum posts to index")
    parser.add_argument("--today", default=None, help="date stamp to record (YYYY-MM-DD)")
    args = parser.parse_args(argv)

    if not args.write and not args.dry_run:
        parser.error("pass --dry-run or --write")

    today = args.today or __import__("datetime").date.today().isoformat()

    fetched = fetch_all(args.limit)
    print(f"fetched metadata for {len(fetched)} post(s)", file=sys.stderr)

    existing = json.loads(SOURCES.read_text(encoding="utf-8"))
    before = len(existing)
    merged, added = merge(existing, fetched, today)

    print(f"{before} existing source node(s); {added} new", file=sys.stderr)

    if args.dry_run:
        for node in merged[before:]:
            print(f"  + {node['id']}  {node['published']}  {node['label']}", file=sys.stderr)
        return 0

    merged.sort(key=lambda n: (n.get("published") or "", n["id"]))
    SOURCES.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {SOURCES} ({len(merged)} source nodes)", file=sys.stderr)
    print("next: PYTHONPATH=src python3 -m graphify validate && PYTHONPATH=src python3 -m graphify build", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
