"""Tests for the audit and maintenance tooling.

Deliberately does not call ``weekly_report.assemble``: that shells out to
``python -m unittest discover``, which would re-enter this suite. Only the pure
functions are exercised here.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import coverage_audit  # noqa: E402
import refresh_corpus  # noqa: E402
import weekly_report  # noqa: E402
from graphify.model import load_graph  # noqa: E402

GRAPH = load_graph()
GAPS = coverage_audit.load_gaps()
REPORT = coverage_audit.audit(GRAPH, GAPS)

IMPACTS = {"high", "medium", "low", "out_of_scope"}
STATUSES = {"not_modelled", "partially_modelled", "deliberately_excluded", "not_covered_by_series"}


class TestGapRegister(unittest.TestCase):
    def test_register_is_populated(self):
        self.assertGreaterEqual(len(GAPS), 10, "the declared-gap register looks suspiciously empty")

    def test_ids_are_unique_and_prefixed(self):
        ids = [g["id"] for g in GAPS]
        self.assertEqual(len(ids), len(set(ids)))
        for gap_id in ids:
            self.assertTrue(gap_id.startswith("gap:"), gap_id)

    def test_required_fields_present(self):
        for gap in GAPS:
            for key in ("theme", "why_it_matters", "impact", "status"):
                self.assertTrue(gap.get(key), f"{gap['id']} missing {key}")
            self.assertIn(gap["impact"], IMPACTS, gap["id"])
            self.assertIn(gap["status"], STATUSES, gap["id"])

    def test_covered_by_references_real_nodes(self):
        """A gap claiming partial coverage must point at nodes that exist."""
        for gap in GAPS:
            for node_id in gap.get("covered_by", []):
                self.assertIn(node_id, GRAPH.nodes, f"{gap['id']} references unknown node {node_id}")

    def test_partially_modelled_gaps_declare_what_covers_them(self):
        for gap in GAPS:
            if gap["status"] == "partially_modelled":
                self.assertTrue(gap.get("covered_by"), f"{gap['id']} claims partial coverage but names nothing")


class TestAudit(unittest.TestCase):
    def test_structural_coverage_is_complete(self):
        self.assertEqual(REPORT["structural"]["integrity_problems"], [])
        self.assertEqual(REPORT["structural"]["thin_pillars"], [])
        self.assertEqual(REPORT["verdict"]["structural_coverage"], "complete")

    def test_density_covers_every_pillar(self):
        self.assertEqual(len(REPORT["structural"]["density"]), len(GRAPH.by_type("pillar")))

    def test_citation_coverage_is_substantial_and_counted(self):
        citation = REPORT["citation"]
        self.assertLessEqual(citation["coverage_ratio"], 1.0, "ratio must be capped at 1.0")
        self.assertGreaterEqual(citation["coverage_ratio"], 0.95)
        self.assertIn("counted", citation["series_estimate_basis"])
        self.assertEqual(REPORT["verdict"]["citation_coverage"], "substantial")

    def test_thematic_coverage_is_verified_against_the_corpus(self):
        thematic = REPORT["thematic"]
        self.assertTrue(thematic["measurable"])
        self.assertEqual(REPORT["verdict"]["thematic_coverage"], "verified_against_corpus")
        self.assertTrue(thematic["verified_against_corpus"], "no gap carries a series_titles count")

    def test_refuted_assumptions_are_recorded_not_deleted(self):
        """Assumptions the corpus disproved stay in the register as a record."""
        self.assertTrue(REPORT["thematic"]["refuted"], "no refuted entries retained")
        for gap_id in REPORT["thematic"]["refuted"]:
            gap = next(g for g in GAPS if g["id"] == gap_id)
            # "Not covered" means absent or, at most, one incidental mention.
            self.assertLessEqual(gap["series_titles"], 1, f"{gap_id} has too many instalments to call refuted")
            self.assertTrue(gap.get("note"), f"{gap_id} should say what was assumed and why it was wrong")

    def test_rubric_risks_are_surfaced(self):
        areas = {r["area"] for r in REPORT["recommendations"]}
        self.assertTrue(REPORT["thematic"]["rubric_risks"])
        for gap_id in REPORT["thematic"]["rubric_risks"]:
            self.assertIn(gap_id, areas, f"{gap_id} is a rubric risk but is not recommended")

    def test_high_impact_gaps_become_recommendations(self):
        areas = {r["area"] for r in REPORT["recommendations"]}
        for gap in GAPS:
            if gap["impact"] != "high":
                continue
            if gap["status"] in ("deliberately_excluded", "not_covered_by_series"):
                continue
            self.assertIn(gap["id"], areas, f"{gap['id']} is high impact but not recommended")

    def test_out_of_scope_gaps_do_not_nag(self):
        areas = {r["area"] for r in REPORT["recommendations"]}
        for gap in GAPS:
            if gap["status"] == "deliberately_excluded":
                self.assertNotIn(gap["id"], areas, f"{gap['id']} is excluded but still recommended")

    def test_evidence_references_resolve_to_indexed_sources(self):
        for gap in GAPS:
            for source_id in gap.get("evidence", []):
                node = GRAPH.get(source_id)
                self.assertIsNotNone(node, f"{gap['id']} cites unknown source {source_id}")
                self.assertEqual(node["type"], "source")

    def test_every_gap_carries_corpus_evidence(self):
        """A gap without a title count has not been checked against the corpus."""
        for gap in GAPS:
            self.assertIn("series_titles", gap, f"{gap['id']} has no series_titles count")
            self.assertIsInstance(gap["series_titles"], int)

    def test_recommendations_are_ordered_by_priority(self):
        order = {"blocking": 0, "high": 1, "medium": 2, "low": 3}
        ranks = [order[r["priority"]] for r in REPORT["recommendations"]]
        self.assertEqual(ranks, sorted(ranks))

    def test_thin_pillar_is_detected(self):
        """Strip a pillar's tests and the audit must notice."""
        graph = load_graph()
        victim = "pillar:coherence"
        graph.edges = [
            e
            for e in graph.edges
            if not (e.type == "IN_PILLAR" and e.dst == victim and graph.nodes[e.src]["type"] == "test")
        ]
        graph.index()
        report = coverage_audit.audit(graph, GAPS)
        self.assertIn(victim, [t["pillar"] for t in report["structural"]["thin_pillars"]])
        self.assertEqual(report["verdict"]["structural_coverage"], "incomplete")

    def test_integrity_problems_produce_a_blocking_recommendation(self):
        broken = copy.deepcopy(REPORT)
        broken["structural"]["integrity_problems"] = ["something is wrong"]
        recs = coverage_audit.recommend(broken, GAPS)
        self.assertEqual(recs[0]["priority"], "blocking")

    def test_markdown_renders_every_section(self):
        text = coverage_audit.render_markdown(REPORT)
        for heading in ("# Coverage audit", "## Nodes", "## Density by pillar", "## Recommendations", "## Declared thematic gaps"):
            self.assertIn(heading, text)


class TestRefreshCorpus(unittest.TestCase):
    def test_slug_becomes_a_clean_id(self):
        self.assertEqual(refresh_corpus._slug_to_id("Strategic-Choice_Chartering"), "src:strategic_choice_chartering")
        self.assertEqual(refresh_corpus._slug_to_id("2025-06-02_through-thick-thin"), "src:through_thick_thin")

    def test_trailing_hash_is_stripped(self):
        self.assertEqual(refresh_corpus._slug_to_id("fixing-strategy-7157f4b4c9ac"), "src:fixing_strategy")

    def test_node_requires_a_title_and_url(self):
        self.assertIsNone(refresh_corpus.to_source_node({"title": "", "canonical_url": "https://x/y"}))
        self.assertIsNone(refresh_corpus.to_source_node({"title": "T", "canonical_url": None}))

    def test_node_never_carries_body_text(self):
        """The indexer must stay metadata-only; a body field must not survive."""
        node = refresh_corpus.to_source_node(
            {
                "title": "A Post",
                "canonical_url": "https://example.test/p/a-post",
                "post_date": "2026-01-05T00:00:00Z",
                "slug": "a-post",
                "body_html": "<p>should never be carried</p>",
            }
        )
        self.assertIsNotNone(node)
        self.assertNotIn("body_html", node)
        self.assertFalse(node["full_text_ingested"])
        self.assertEqual(node["published"], "2026-01-05")
        for value in node.values():
            self.assertNotIn("should never be carried", str(value))

    def test_keep_list_excludes_body_fields(self):
        for field in refresh_corpus.KEEP:
            self.assertNotIn("body", field)

    def test_merge_adds_new_posts(self):
        existing = [{"id": "src:known", "type": "source", "label": "Known", "url": "https://example.test/p/known"}]
        merged, added, _reconciled = refresh_corpus.merge(
            existing,
            [{"title": "Fresh", "canonical_url": "https://example.test/p/fresh", "post_date": "2026-02-01", "slug": "fresh"}],
            "2026-02-02",
        )
        self.assertEqual(added, 1)
        self.assertEqual(merged[-1]["id"], "src:fresh")
        self.assertEqual(merged[-1]["verified_on"], "2026-02-02")

    def test_merge_is_idempotent_on_url(self):
        existing = [
            {
                "id": "src:known",
                "type": "source",
                "label": "Known",
                "url": "https://example.test/p/known",
                "themes": ["hand written"],
            }
        ]
        post = {"title": "Known", "canonical_url": "https://example.test/p/known", "post_date": "2026-01-01", "slug": "known"}
        merged, added, _ = refresh_corpus.merge(existing, [post], "2026-02-02")
        merged, added_again, _ = refresh_corpus.merge(merged, [post], "2026-02-02")
        self.assertEqual((added, added_again), (0, 0))
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["themes"], ["hand written"], "hand-written fields must survive a refresh")

    def test_merge_disambiguates_colliding_ids(self):
        existing = [{"id": "src:fresh", "type": "source", "label": "Old", "url": "https://example.test/p/other"}]
        merged, added, _reconciled = refresh_corpus.merge(
            existing,
            [{"title": "Fresh", "canonical_url": "https://example.test/p/fresh", "post_date": "", "slug": "fresh"}],
            "2026-02-02",
        )
        self.assertEqual(added, 1)
        self.assertEqual(merged[-1]["id"], "src:fresh_2")

    def test_collect_reports_errors_instead_of_raising(self):
        original = refresh_corpus.fetch_page
        refresh_corpus.fetch_page = lambda offset, timeout=30.0: (_ for _ in ()).throw(OSError("no network"))
        try:
            posts, error = refresh_corpus.collect(10)
        finally:
            refresh_corpus.fetch_page = original
        self.assertEqual(posts, [])
        self.assertIn("no network", error)

    def test_collect_paginates_then_stops(self):
        pages = {0: [{"title": f"P{i}", "canonical_url": f"https://x/{i}", "post_date": "", "slug": str(i)} for i in range(50)], 50: []}
        original = refresh_corpus.fetch_page
        refresh_corpus.fetch_page = lambda offset, timeout=30.0: pages.get(offset, [])
        try:
            posts, error = refresh_corpus.collect(400)
        finally:
            refresh_corpus.fetch_page = original
        self.assertIsNone(error)
        self.assertEqual(len(posts), 50)


class TestWeeklyReport(unittest.TestCase):
    def _report(self, status: str, **overrides) -> dict:
        report = {
            "checked_on": "2026-08-19",
            "status": status,
            "exit_code": {"clean": 0, "attention": 1, "broken": 2}[status],
            "corpus": {"skipped": False, "reachable": True, "fetched": 270, "existing": 35, "new_count": 0, "new_posts": [], "error": None},
            "checks": [{"name": "graph validation", "ok": True, "code": 0, "output": ""}],
            "failed_checks": [],
            "audit": REPORT,
            "high_priority_recommendations": [],
        }
        report.update(overrides)
        return report

    def test_exit_codes_are_distinct(self):
        self.assertEqual((weekly_report.CLEAN, weekly_report.ATTENTION, weekly_report.BROKEN), (0, 1, 2))

    def test_clean_report_renders(self):
        text = weekly_report.render(self._report("clean"))
        self.assertIn("Clean", text)
        self.assertIn("## Checks", text)
        self.assertIn("## Coverage", text)

    def test_new_posts_are_listed_and_flagged_as_unjudged(self):
        report = self._report(
            "attention",
            corpus={
                "skipped": False,
                "reachable": True,
                "fetched": 271,
                "existing": 35,
                "new_count": 1,
                "new_posts": [{"published": "2026-08-17", "title": "A New Piece", "url": "https://example.test/p/new"}],
                "error": None,
            },
        )
        text = weekly_report.render(report)
        self.assertIn("A New Piece", text)
        self.assertIn("not yet in the graph", text)
        self.assertIn("judgement call", text)

    def test_pipe_in_a_title_is_escaped(self):
        report = self._report(
            "attention",
            corpus={
                "skipped": False, "reachable": True, "fetched": 1, "existing": 0, "new_count": 1,
                "new_posts": [{"published": "2026-08-17", "title": "Cost | Differentiation", "url": "https://x/y"}],
                "error": None,
            },
        )
        self.assertIn("Cost \\| Differentiation", weekly_report.render(report))

    def test_unreachable_archive_is_not_reported_as_a_content_finding(self):
        report = self._report(
            "attention",
            corpus={"skipped": False, "reachable": False, "new_count": 0, "new_posts": [], "error": "blocked"},
        )
        text = weekly_report.render(report)
        self.assertIn("unreachable", text)
        self.assertIn("network result, not a content result", text)

    def test_failed_check_output_is_included(self):
        report = self._report(
            "broken",
            checks=[{"name": "test suite", "ok": False, "code": 1, "output": "AssertionError: boom"}],
            failed_checks=["test suite"],
        )
        text = weekly_report.render(report)
        self.assertIn("**FAIL**", text)
        self.assertIn("AssertionError: boom", text)

    def test_skipped_network_is_stated(self):
        report = self._report("clean", corpus={"skipped": True, "reachable": None, "new_count": 0, "new_posts": []})
        self.assertIn("skipped", weekly_report.render(report))

    def test_check_corpus_honours_skip_network(self):
        result = weekly_report.check_corpus(skip_network=True, limit=10)
        self.assertTrue(result["skipped"])
        self.assertEqual(result["new_count"], 0)


class TestAttributionScripts(unittest.TestCase):
    """The AI attribution gate, ported from stock-analyzer.

    The two selector behaviours below are the reason trailer-block.sh exists at
    all; both correspond to false positives that reached a default branch in the
    original repo.
    """

    SCRIPTS = ROOT / "scripts" / "ai-attribution"

    def _run(self, script: str, stdin: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(self.SCRIPTS / script), "-"] if script != "trailer-block.sh"
            else ["bash", str(self.SCRIPTS / script)],
            input=stdin,
            capture_output=True,
            text=True,
        )

    def test_scripts_are_syntactically_valid(self):
        targets = list(self.SCRIPTS.glob("*.sh")) + [ROOT / ".githooks" / "prepare-commit-msg"]
        self.assertTrue(targets)
        for path in targets:
            with self.subTest(script=path.name):
                self.assertEqual(subprocess.run(["bash", "-n", str(path)]).returncode, 0)

    def test_selects_trailer_block_that_is_not_the_last_paragraph(self):
        message = (
            "Change\n\nAI-Model: claude-opus-5\nAI-Session: abc-123\n\n"
            "Co-authored-by: someone <a@b.c>\nNotes appended by a review bot.\n"
        )
        out = self._run("trailer-block.sh", message).stdout
        self.assertIn("AI-Model: claude-opus-5", out)
        self.assertNotIn("review bot", out)

    def test_prose_quoting_the_format_does_not_win_over_a_real_block(self):
        message = (
            "Docs change\n\nThis file explains AI-Model: some-example inline.\n\n"
            "AI-Model: claude-opus-5\nAI-Session: abc-123\n"
        )
        out = self._run("trailer-block.sh", message).stdout
        self.assertIn("claude-opus-5", out)
        self.assertNotIn("some-example", out)

    def test_folded_values_are_rejoined(self):
        message = "x\n\nAI-Model: claude-opus-5\nAI-Transcript: /a/long\n  /path.jsonl\n"
        out = self._run("trailer-block.sh", message).stdout
        self.assertIn("/a/long/path.jsonl", out)

    def test_pr_body_rejects_empty_fields(self):
        result = self._run("check-pr-body.sh", "Body\n\nAI-Model:\nAI-Session:\n")
        self.assertEqual(result.returncode, 1)
        self.assertIn("missing AI-Model", result.stderr)

    def test_pr_body_rejects_placeholders(self):
        result = self._run("check-pr-body.sh", "Body\n\nAI-Model: unknown\nAI-Session: TBD\n")
        self.assertEqual(result.returncode, 1)
        self.assertIn("placeholder", result.stderr)

    def test_pr_body_accepts_real_values(self):
        result = self._run(
            "check-pr-body.sh", "Body\n\nAI-Model: claude-opus-5\nAI-Session: b22aa90d\n"
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_pr_body_accepts_an_explicit_no_ai_declaration(self):
        result = self._run("check-pr-body.sh", "Body\n\nAI-Assisted: none\n")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_grandfathered_history_is_exempt(self):
        """Adopting the check must not flag the history that predates it."""
        result = subprocess.run(
            ["bash", str(self.SCRIPTS / "check-commits.sh"), "81e0c55..5c262d6"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("exempt", result.stdout)

    def test_commit_hook_refuses_rather_than_stamping_a_placeholder(self):
        """The key lesson from the source policy: 'unknown' passes a presence check."""
        hook = (ROOT / ".githooks" / "prepare-commit-msg").read_text(encoding="utf-8")
        self.assertNotIn("AI-Model: unknown", hook)
        self.assertIn("exit 1", hook)

    def test_checker_rejects_unknown_as_a_value(self):
        checker = (self.SCRIPTS / "check-commits.sh").read_text(encoding="utf-8")
        self.assertIn("unknown", checker, "the CI side must also reject 'unknown'")


class TestCommitHookBehaviour(unittest.TestCase):
    """Run the commit hook for real in a throwaway repository.

    `bash -n` cannot catch what this catches. The first version of this hook ended
    with `[ -n "$TRANSCRIPT" ] && printf ...`; under `set -e` that trailing test
    became the block's exit status whenever there was no transcript, so the hook
    exited 1 and git aborted the commit with no diagnostic at all.
    """

    HOOK = ROOT / ".githooks" / "prepare-commit-msg"

    def _repo(self, stack) -> Path:
        import tempfile

        tmp = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        hooks = tmp / ".githooks"
        hooks.mkdir()
        (hooks / "prepare-commit-msg").write_bytes(self.HOOK.read_bytes())
        (hooks / "prepare-commit-msg").chmod(0o755)
        for args in (
            ["init", "-q", "."],
            ["config", "user.email", "t@example.test"],
            ["config", "user.name", "Test"],
            ["config", "core.hooksPath", ".githooks"],
        ):
            subprocess.run(["git", *args], cwd=tmp, check=True, capture_output=True)
        (tmp / "f.txt").write_text("x")
        subprocess.run(["git", "add", "f.txt"], cwd=tmp, check=True, capture_output=True)
        return tmp

    def _commit(self, repo: Path, env: dict, message: str = "probe: change") -> subprocess.CompletedProcess:
        import os

        merged = {**os.environ, **env}
        for key, value in env.items():
            if value is None:
                merged.pop(key, None)
        return subprocess.run(
            ["git", "commit", "-F", "-"],
            cwd=repo,
            input=message,
            text=True,
            capture_output=True,
            env=merged,
        )

    def _message(self, repo: Path) -> str:
        return subprocess.run(
            ["git", "log", "-1", "--format=%B"], cwd=repo, capture_output=True, text=True
        ).stdout

    def test_appends_trailers_inside_a_session(self):
        import contextlib

        with contextlib.ExitStack() as stack:
            repo = self._repo(stack)
            subprocess.run(["git", "config", "ai.model", "claude-opus-5"], cwd=repo, check=True, capture_output=True)
            result = self._commit(repo, {"CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": "sess-123"})
            self.assertEqual(result.returncode, 0, result.stderr)
            message = self._message(repo)
            self.assertIn("AI-Model: claude-opus-5", message)
            self.assertIn("AI-Session: sess-123", message)

    def test_declares_none_outside_a_session(self):
        import contextlib

        with contextlib.ExitStack() as stack:
            repo = self._repo(stack)
            result = self._commit(
                repo,
                {"CLAUDECODE": None, "CLAUDE_CODE_SESSION_ID": None, "CLAUDE_CODE_REMOTE_SESSION_ID": None},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("AI-Assisted: none", self._message(repo))

    def test_refuses_when_the_model_is_unknown(self):
        """The whole point: a placeholder would pass a presence check."""
        import contextlib

        with contextlib.ExitStack() as stack:
            repo = self._repo(stack)
            result = self._commit(
                repo,
                {
                    "CLAUDECODE": "1",
                    "CLAUDE_CODE_SESSION_ID": "sess-456",
                    "AI_ATTRIBUTION_STATE_DIR": str(repo / "no-such-dir"),
                },
            )
            self.assertNotEqual(result.returncode, 0, "hook should refuse")
            self.assertIn("unknown", result.stderr)
            log = subprocess.run(["git", "log", "--oneline"], cwd=repo, capture_output=True, text=True)
            self.assertEqual(log.stdout.strip(), "", "no commit should have been created")

    def test_hook_output_is_produced_by_the_state_file_path(self):
        """The primary path: model and transcript come from the SessionStart recorder."""
        import contextlib

        with contextlib.ExitStack() as stack:
            repo = self._repo(stack)
            state = repo / "state"
            state.mkdir()
            (state / "sess-789.env").write_text(
                "AI_MODEL='claude-opus-5'\nAI_TRANSCRIPT='/tmp/t.jsonl'\n"
            )
            result = self._commit(
                repo,
                {
                    "CLAUDECODE": "1",
                    "CLAUDE_CODE_SESSION_ID": "sess-789",
                    "AI_ATTRIBUTION_STATE_DIR": str(state),
                },
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            message = self._message(repo)
            self.assertIn("AI-Model: claude-opus-5", message)
            self.assertIn("AI-Transcript: /tmp/t.jsonl", message)

    def test_session_start_recorder_writes_a_sourceable_state_file(self):
        import contextlib, tempfile, os

        with contextlib.ExitStack() as stack:
            tmp = Path(stack.enter_context(tempfile.TemporaryDirectory()))
            result = subprocess.run(
                ["python3", str(ROOT / ".claude" / "hooks" / "session_start.py")],
                input=json.dumps(
                    {"session_id": "abc", "model": "claude-opus-5", "transcript_path": "/tmp/x.jsonl"}
                ),
                text=True,
                capture_output=True,
                env={**os.environ, "AI_ATTRIBUTION_STATE_DIR": str(tmp)},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            written = (tmp / "abc.env").read_text()
            self.assertIn("AI_MODEL='claude-opus-5'", written)
            self.assertIn("AI_TRANSCRIPT='/tmp/x.jsonl'", written)


class TestWorkflowDefinition(unittest.TestCase):
    PATH = ROOT / ".github" / "workflows" / "weekly-corpus-check.yml"
    ALL = ROOT / ".github" / "workflows"

    @staticmethod
    def _load(path: Path) -> dict:
        try:
            import yaml
        except ImportError:  # pragma: no cover
            raise unittest.SkipTest("pyyaml not installed")
        return yaml.safe_load(path.read_text(encoding="utf-8"))

    def test_every_workflow_parses(self):
        files = sorted(self.ALL.glob("*.yml"))
        self.assertGreaterEqual(len(files), 4, "expected ci, attribution, audit and corpus workflows")
        for path in files:
            with self.subTest(workflow=path.name):
                doc = self._load(path)
                self.assertIn("jobs", doc, path.name)
                self.assertTrue(doc.get("on") or doc.get(True), f"{path.name} has no triggers")

    def test_ci_runs_the_load_bearing_checks(self):
        doc = self._load(self.ALL / "ci.yml")
        steps = json.dumps(doc["jobs"]["check"]["steps"])
        for command in ("graphify validate", "unittest discover", "coverage_audit.py --strict", "graphify build"):
            self.assertIn(command, steps, f"CI does not run {command}")

    def test_attribution_check_exempts_bot_pull_requests(self):
        doc = self._load(self.ALL / "ai-attribution.yml")
        self.assertIn("Bot", json.dumps(doc["jobs"]["check"].get("if", "")))

    def test_attribution_check_uses_full_history(self):
        """A shallow clone cannot resolve a base..head commit range."""
        doc = self._load(self.ALL / "ai-attribution.yml")
        steps = doc["jobs"]["check"]["steps"]
        checkout = next(s for s in steps if str(s.get("uses", "")).startswith("actions/checkout"))
        self.assertEqual(checkout.get("with", {}).get("fetch-depth"), 0)

    def test_audit_can_open_an_issue(self):
        doc = self._load(self.ALL / "ai-attribution-audit.yml")
        self.assertEqual(doc["permissions"].get("issues"), "write")

    def test_workflow_exists_and_parses(self):
        try:
            import yaml
        except ImportError:  # pragma: no cover
            self.skipTest("pyyaml not installed")
        doc = yaml.safe_load(self.PATH.read_text(encoding="utf-8"))
        self.assertIn("jobs", doc)
        # 'on' is parsed as boolean True by YAML 1.1
        triggers = doc.get("on") or doc.get(True)
        self.assertIn("schedule", triggers)
        self.assertIn("workflow_dispatch", triggers)

    def test_schedule_is_weekly(self):
        try:
            import yaml
        except ImportError:  # pragma: no cover
            self.skipTest("pyyaml not installed")
        doc = yaml.safe_load(self.PATH.read_text(encoding="utf-8"))
        triggers = doc.get("on") or doc.get(True)
        cron = triggers["schedule"][0]["cron"]
        self.assertEqual(len(cron.split()), 5)
        day_of_week = cron.split()[4]
        self.assertNotEqual(day_of_week, "*", "a '*' day-of-week would run daily, not weekly")

    def test_permissions_allow_filing_an_issue(self):
        try:
            import yaml
        except ImportError:  # pragma: no cover
            self.skipTest("pyyaml not installed")
        doc = yaml.safe_load(self.PATH.read_text(encoding="utf-8"))
        self.assertEqual(doc["permissions"].get("issues"), "write")


if __name__ == "__main__":
    unittest.main()
