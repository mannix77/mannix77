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
    stem = re.sub(r"^\d{4}_\d{2}_\d{2}_", "", stem)  # leading date
    # Trailing content hash, sometimes with "html" glued straight onto it.
    # Strip before truncating, or truncation leaves half a hash behind.
    stem = re.sub(r"_?[0-9a-f]{8,}(html)?$", "", stem)
    stem = re.sub(r"_?html$", "", stem)
    return f"src:{stem[:60].strip('_') or 'post'}"


def _title_key(title: str) -> str:
    """Normalised title, for matching a fetched post to a hand-written entry."""
    return re.sub(r"[^a-z0-9]+", "", (title or "").lower())


def fetch_page(offset: int, timeout: float = 30.0) -> list[dict[str, Any]]:
    url = f"{ARCHIVE_API}?sort=new&limit={PAGE_SIZE}&offset={offset}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"unexpected archive response shape: {type(payload).__name__}")
    return [{k: post.get(k) for k in KEEP} for post in payload]


def collect(limit: int) -> tuple[list[dict[str, Any]], str | None]:
    """Fetch metadata, never raising. Returns (posts, error_message_or_None).

    Used by CI, which needs to distinguish "the archive says nothing is new" from
    "the archive was unreachable" and carry on either way.
    """
    posts: list[dict[str, Any]] = []
    seen: set[str] = set()
    offset = 0
    while len(posts) < limit:
        try:
            page = fetch_page(offset)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, OSError) as exc:
            message = f"archive unreachable at offset {offset}: {exc}"
            if not posts:
                return [], message
            print(f"stopping early - {message}", file=sys.stderr)
            break
        if not page:
            break

        fresh = [p for p in page if p.get("canonical_url") and p["canonical_url"] not in seen]
        for post in fresh:
            seen.add(post["canonical_url"])
        posts.extend(fresh)

        # Advance by what the page actually returned, not by the requested size.
        # This endpoint can return fewer rows than asked for while more remain;
        # stepping a fixed PAGE_SIZE skips those rows silently.
        offset += len(page)
        if not fresh:
            break
    return posts[:limit], None


def fetch_all(limit: int) -> list[dict[str, Any]]:
    posts, error = collect(limit)
    if error and not posts:
        raise SystemExit(
            f"{error}\n"
            "If this is a sandboxed environment, outbound access to substack.com is "
            "probably blocked - run this from somewhere with network access."
        )
    return posts


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


def merge(
    existing: list[dict[str, Any]], fetched: list[dict[str, Any]], today: str
) -> tuple[list[dict[str, Any]], int, int]:
    """Fold fetched metadata into the existing index.

    Matching is by URL first, then by normalised title. The title pass matters:
    hand-written entries were added from search results and their URLs can differ
    from the archive's canonical form. Matching on title lets those entries keep
    their ids - and therefore the citation edges pointing at them - while their
    URL is corrected to the canonical one.

    Returns (nodes, added, reconciled).
    """
    by_url = {node.get("url"): node for node in existing}
    by_title = {_title_key(node.get("label", "")): node for node in existing if node.get("label")}
    by_id = {node["id"]: node for node in existing}
    confirmed = by_url_confirmed(fetched)
    added = reconciled = 0

    for post in fetched:
        node = to_source_node(post)
        if node is None:
            continue
        node["verified_on"] = today

        current = by_url.get(node["url"])
        if current is None:
            candidate = by_title.get(_title_key(node["label"]))
            # Only reconcile against an entry whose URL the archive did not confirm.
            if candidate is not None and candidate.get("url") not in confirmed:
                current = candidate
                if current.get("url") != node["url"]:
                    current["url_previous"] = current.get("url")
                    current["url"] = node["url"]
                    by_url[node["url"]] = current
                    reconciled += 1

        if current is not None:
            for key in ("published", "label"):
                if not current.get(key) and node.get(key):
                    current[key] = node[key]
            current["verified"] = "archive_api"
            current["verified_on"] = today
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
        by_title.setdefault(_title_key(node["label"]), node)
        added += 1

    return existing, added, reconciled


def by_url_confirmed(fetched: list[dict[str, Any]]) -> set[str]:
    """URLs the archive itself reported, so an exact match is never overwritten."""
    return {p.get("canonical_url") for p in fetched if p.get("canonical_url")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--write", action="store_true", help="write data/sources.json in place")
    parser.add_argument("--dry-run", action="store_true", help="report what would change and exit")
    parser.add_argument("--limit", type=int, default=400, help="maximum posts to index")
    parser.add_argument("--today", default=None, help="date stamp to record (YYYY-MM-DD)")
    parser.add_argument("--report", help="write a machine-readable summary here (for CI)")
    parser.add_argument(
        "--tolerate-offline",
        action="store_true",
        help="exit 0 when the archive is unreachable, so a scheduled job can carry on",
    )
    args = parser.parse_args(argv)

    if not args.write and not args.dry_run:
        parser.error("pass --dry-run or --write")

    today = args.today or __import__("datetime").date.today().isoformat()

    fetched, error = collect(args.limit)
    if error:
        print(error, file=sys.stderr)
    print(f"fetched metadata for {len(fetched)} post(s)", file=sys.stderr)

    existing = json.loads(SOURCES.read_text(encoding="utf-8"))
    before = len(existing)
    merged, added, reconciled = merge(existing, fetched, today)
    new_nodes = merged[before:]

    print(
        f"{before} existing source node(s); {added} new; {reconciled} URL(s) reconciled to canonical",
        file=sys.stderr,
    )

    if args.report:
        Path(args.report).write_text(
            json.dumps(
                {
                    "checked_on": today,
                    "reachable": error is None,
                    "error": error,
                    "fetched": len(fetched),
                    "existing": before,
                    "new_count": added,
                    "reconciled_count": reconciled,
                    "new_posts": [
                        {"id": n["id"], "published": n["published"], "title": n["label"], "url": n["url"]}
                        for n in new_nodes
                    ],
                    "written": bool(args.write),
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

    if error and not fetched:
        return 0 if args.tolerate_offline else 1

    if args.dry_run:
        for node in new_nodes:
            print(f"  + {node['id']}  {node['published']}  {node['label']}", file=sys.stderr)
        return 0

    merged.sort(key=lambda n: (n.get("published") or "", n["id"]))
    SOURCES.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {SOURCES} ({len(merged)} source nodes)", file=sys.stderr)
    print("next: PYTHONPATH=src python3 -m graphify validate && PYTHONPATH=src python3 -m graphify build", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
