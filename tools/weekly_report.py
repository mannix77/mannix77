#!/usr/bin/env python3
"""Weekly maintenance run: check the archive, audit coverage, validate, test, build.

Designed for the scheduled workflow in ``.github/workflows/weekly-corpus-check.yml``,
but it runs identically by hand.

Exit codes, which the workflow uses to decide whether to file anything:

    0  clean - nothing new upstream, all checks pass
    1  attention - new instalments upstream, or coverage recommendations at high
       priority, or the archive was unreachable. Nothing is broken.
    2  broken - the graph fails validation, the tests fail, or the build fails.

Usage:
    python3 tools/weekly_report.py                          # markdown to stdout
    python3 tools/weekly_report.py --out report.md --json report.json
    python3 tools/weekly_report.py --skip-network            # offline check only
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import coverage_audit  # noqa: E402
from graphify.model import load_graph  # noqa: E402

CLEAN, ATTENTION, BROKEN = 0, 1, 2


def _run(args: list[str], timeout: int = 900) -> dict[str, Any]:
    """Run a subprocess and capture the outcome."""
    env_note = {"PYTHONPATH": str(ROOT / "src")}
    try:
        proc = subprocess.run(
            args,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**__import__("os").environ, **env_note},
        )
    except subprocess.TimeoutExpired:
        return {"command": " ".join(args), "ok": False, "code": None, "output": f"timed out after {timeout}s"}
    output = (proc.stdout or "") + (proc.stderr or "")
    return {
        "command": " ".join(args),
        "ok": proc.returncode == 0,
        "code": proc.returncode,
        "output": output.strip()[-4000:],
    }


def check_corpus(skip_network: bool, limit: int) -> dict[str, Any]:
    if skip_network:
        return {"skipped": True, "reachable": None, "new_count": 0, "new_posts": [], "error": None}
    with tempfile.TemporaryDirectory() as tmp:
        report_path = Path(tmp) / "corpus.json"
        result = _run(
            [
                sys.executable,
                "tools/refresh_corpus.py",
                "--dry-run",
                "--tolerate-offline",
                "--limit",
                str(limit),
                "--report",
                str(report_path),
            ]
        )
        if report_path.exists():
            payload = json.loads(report_path.read_text(encoding="utf-8"))
            payload["skipped"] = False
            return payload
    return {
        "skipped": False,
        "reachable": False,
        "new_count": 0,
        "new_posts": [],
        "error": f"refresh_corpus produced no report: {result['output'][:400]}",
    }


def run_checks() -> list[dict[str, Any]]:
    return [
        {"name": "graph validation", **_run([sys.executable, "-m", "graphify", "validate"])},
        {"name": "test suite", **_run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."])},
        {"name": "build artefacts", **_run([sys.executable, "-m", "graphify", "build"])},
        {
            "name": "coverage audit (strict)",
            **_run([sys.executable, "tools/coverage_audit.py", "--strict", "--quiet"]),
        },
    ]


def assemble(skip_network: bool, limit: int, today: str) -> dict[str, Any]:
    corpus = check_corpus(skip_network, limit)
    checks = run_checks()
    audit = coverage_audit.audit(load_graph(), coverage_audit.load_gaps())

    broken = [c for c in checks if not c["ok"]]
    high = [r for r in audit["recommendations"] if r["priority"] in ("blocking", "high")]

    if broken:
        status, exit_code = "broken", BROKEN
    elif corpus.get("new_count") or high or corpus.get("reachable") is False:
        status, exit_code = "attention", ATTENTION
    else:
        status, exit_code = "clean", CLEAN

    return {
        "checked_on": today,
        "status": status,
        "exit_code": exit_code,
        "corpus": corpus,
        "checks": checks,
        "failed_checks": [c["name"] for c in broken],
        "audit": audit,
        "high_priority_recommendations": high,
    }


def render(report: dict[str, Any]) -> str:
    corpus, audit = report["corpus"], report["audit"]
    headline = {
        "clean": "Clean - nothing new upstream, all checks pass.",
        "attention": "Attention - nothing is broken, but there is work to look at.",
        "broken": "Broken - a check is failing and needs a fix.",
    }[report["status"]]

    lines = [
        f"# Weekly corpus check - {report['checked_on']}",
        "",
        f"**{headline}**",
        "",
        "## Upstream",
        "",
    ]

    if corpus.get("skipped"):
        lines.append("Archive check skipped (`--skip-network`).")
    elif corpus.get("reachable") is False:
        lines += [
            f"Archive was **unreachable**: `{corpus.get('error')}`",
            "",
            "Nothing to conclude from this - it is a network result, not a content result. "
            "If it repeats for several weeks, the archive URL or API shape may have changed; "
            "check `ARCHIVE_API` in `tools/refresh_corpus.py`.",
        ]
    else:
        lines.append(
            f"Archive reachable. {corpus.get('fetched', 0)} instalment(s) seen, "
            f"{corpus.get('existing', 0)} already indexed, **{corpus.get('new_count', 0)} new**."
        )
        if corpus.get("new_posts"):
            lines += ["", "| Published | Title |", "|---|---|"]
            for post in corpus["new_posts"][:40]:
                title = str(post["title"]).replace("|", "\\|")
                lines.append(f"| {post['published'] or '?'} | [{title}]({post['url']}) |")
            if len(corpus["new_posts"]) > 40:
                lines.append(f"| … | and {len(corpus['new_posts']) - 40} more |")
            lines += [
                "",
                "These are **not yet in the graph**. Indexing them adds citations; deciding "
                "whether any of them introduces a concept, test or trap the graph lacks is a "
                "judgement call and needs a human or an agent pass.",
            ]

    lines += ["", "## Checks", "", "| Check | Result |", "|---|---|"]
    for check in report["checks"]:
        lines.append(f"| {check['name']} | {'pass' if check['ok'] else '**FAIL**'} |")

    for check in report["checks"]:
        if not check["ok"]:
            lines += [
                "",
                f"<details><summary>Output: {check['name']}</summary>",
                "",
                "```",
                check["output"] or "(no output)",
                "```",
                "",
                "</details>",
            ]

    verdict = audit["verdict"]
    lines += [
        "",
        "## Coverage",
        "",
        f"- Structural: **{verdict['structural_coverage']}**",
        f"- Citations: **{verdict['citation_coverage']}** "
        f"({audit['citation']['posts_indexed']} posts of an estimated {audit['citation']['series_estimate']})",
        f"- Thematic: **{verdict['thematic_coverage']}** ({audit['thematic']['declared_gaps']} declared gaps)",
        f"- Nodes: {audit['node_total']}",
        "",
        "## Recommendations",
        "",
    ]
    if not audit["recommendations"]:
        lines.append("None.")
    for rec in audit["recommendations"]:
        lines.append(f"- **{rec['priority']}** · `{rec['area']}` — {rec['recommendation']}")

    lines += [
        "",
        "---",
        "",
        "Produced by `tools/weekly_report.py` via `.github/workflows/weekly-corpus-check.yml`. "
        "To change what counts as attention-worthy, edit the thresholds in `tools/coverage_audit.py`; "
        "to stop these entirely, disable that workflow.",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", help="write the markdown report here")
    parser.add_argument("--json", dest="json_out", help="write the raw report here")
    parser.add_argument("--skip-network", action="store_true", help="do not contact the archive")
    parser.add_argument("--limit", type=int, default=400)
    parser.add_argument("--today", default=None)
    parser.add_argument("--always-succeed", action="store_true", help="always exit 0 (for manual runs)")
    args = parser.parse_args(argv)

    report = assemble(args.skip_network, args.limit, args.today or date.today().isoformat())
    markdown = render(report)

    if args.out:
        Path(args.out).write_text(markdown, encoding="utf-8")
    else:
        print(markdown)
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"status={report['status']} exit={report['exit_code']}", file=sys.stderr)
    return 0 if args.always_succeed else report["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
