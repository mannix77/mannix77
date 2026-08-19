"""Test suite. Run: python -m unittest discover -s tests -t . -v"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from graphify import assess, build, interview, query  # noqa: E402
from graphify.model import ID_PREFIX, load_graph, stats, validate  # noqa: E402

GRAPH = load_graph()


class TestIntegrity(unittest.TestCase):
    def test_graph_validates_clean(self):
        self.assertEqual(validate(GRAPH), [], "data files have integrity problems")

    def test_expected_node_types_present(self):
        counts = stats(GRAPH)["nodes"]
        for node_type in ID_PREFIX:
            self.assertGreater(counts.get(node_type, 0), 0, f"no {node_type} nodes")

    def test_every_pillar_has_tests_and_questions(self):
        for pillar in GRAPH.pillars_in_order():
            members = GRAPH.sources_of(pillar["id"], "IN_PILLAR")
            kinds = {m["type"] for m in members}
            self.assertIn("test", kinds, f"{pillar['id']} has no tests")
            self.assertIn("question", kinds, f"{pillar['id']} has no questions")

    def test_every_source_has_a_url(self):
        for source in GRAPH.by_type("source"):
            self.assertTrue(source["url"].startswith("https://"), source["id"])

    def test_no_orphan_concepts(self):
        """Every concept is either tested, related to something, or cited."""
        for concept in GRAPH.by_type("concept"):
            degree = len(GRAPH.out_edges(concept["id"])) + len(GRAPH.in_edges(concept["id"]))
            self.assertGreater(degree, 1, f"{concept['id']} is effectively isolated")

    def test_blocking_tests_exist_and_gate(self):
        blocking = [t for t in GRAPH.by_type("test") if t["severity"] == "blocking"]
        self.assertGreaterEqual(len(blocking), 3)
        gated_by = {e.src for e in GRAPH.edges if e.type == "GATES"}
        self.assertTrue(gated_by, "no GATES edges defined")
        for test_id in gated_by:
            self.assertEqual(GRAPH.node(test_id)["severity"], "blocking", f"{test_id} gates but is not blocking")


class TestQuestionDiscipline(unittest.TestCase):
    """The agent must not author strategy, so the question bank must not either."""

    AUTHORING = re.compile(
        r"\b(you should|i recommend|i suggest|my recommendation|"
        r"here(?:'s| is) (?:a|an|your) (?:draft|example|strawman)|"
        r"i(?:'ll| will) (?:draft|write)|let me (?:draft|write|propose))\b",
        re.IGNORECASE,
    )

    def test_questions_are_questions(self):
        for question in GRAPH.by_type("question"):
            self.assertTrue(
                question["text"].rstrip().endswith("?"),
                f"{question['id']} does not end in a question mark",
            )

    def test_questions_do_not_author(self):
        for question in GRAPH.by_type("question"):
            match = self.AUTHORING.search(question["text"])
            self.assertIsNone(match, f"{question['id']} contains authoring language: {match!r}")

    def test_every_question_has_an_intent_and_a_probe(self):
        for question in GRAPH.by_type("question"):
            self.assertTrue(question["intent"].strip(), question["id"])
            self.assertTrue(question["probes"], f"{question['id']} probes no test")

    def test_openers_and_closers_exist(self):
        kinds = {w for q in GRAPH.by_type("question") for w in q["ask_when"]}
        self.assertIn("opening", kinds)
        self.assertIn("closing", kinds)

    def test_follow_ups_never_cycle_back_on_themselves(self):
        for question in GRAPH.by_type("question"):
            self.assertNotIn(question["id"], question.get("follow_ups", []), question["id"])


class TestAssess(unittest.TestCase):
    def test_empty_state_is_all_unknown(self):
        report = assess.assess(GRAPH, assess.StrategyState())
        self.assertEqual(report["overall_readiness"], 0.0)
        self.assertEqual(report["assessment_coverage"], 0.0)
        self.assertEqual(report["gaps"], [])
        self.assertTrue(report["gated"], "unknown blocking tests should gate downstream pillars")

    def test_all_pass_is_full_readiness(self):
        state = assess.StrategyState(verdicts={t["id"]: "pass" for t in GRAPH.by_type("test")})
        report = assess.assess(GRAPH, state)
        self.assertEqual(report["overall_readiness"], 1.0)
        self.assertEqual(report["assessment_coverage"], 1.0)
        self.assertEqual(report["blocking"], [])
        self.assertEqual(report["gated"], [])

    def test_blocking_failure_surfaces(self):
        state = assess.StrategyState(verdicts={"test:contains_a_bet": "fail"})
        report = assess.assess(GRAPH, state)
        self.assertEqual([g["test"] for g in report["blocking"]], ["test:contains_a_bet"])
        self.assertIn("pillar:how_to_win", [g["pillar"] for g in report["gated"]])

    def test_gaps_are_ranked_by_priority(self):
        state = assess.StrategyState(
            verdicts={
                "test:arena_can_support_returns": "fail",  # minor, weight 2
                "test:htw_single_logic": "fail",  # major, weight 5
            }
        )
        report = assess.assess(GRAPH, state)
        self.assertEqual(report["gaps"][0]["test"], "test:htw_single_logic")

    def test_partial_earns_half_credit(self):
        one = GRAPH.by_type("test")[0]["id"]
        full = assess.assess(GRAPH, assess.StrategyState(verdicts={one: "pass"}))["pillars"]
        half = assess.assess(GRAPH, assess.StrategyState(verdicts={one: "partial"}))["pillars"]
        pillar = GRAPH.node(one)["pillar"]
        full_score = next(p["readiness"] for p in full if p["pillar"] == pillar)
        half_score = next(p["readiness"] for p in half if p["pillar"] == pillar)
        self.assertAlmostEqual(half_score * 2, full_score, places=3)

    def test_missing_required_slots_reported(self):
        report = assess.assess(GRAPH, assess.StrategyState())
        wtp = next(p for p in report["pillars"] if p["pillar"] == "pillar:where_to_play")
        self.assertIn("slot:wtp_exclusions", wtp["missing_required_slots"])

    def test_state_validation_catches_bad_input(self):
        problems = assess.validate_state(
            GRAPH,
            assess.StrategyState(
                slots={"slot:nope": "filled"},
                verdicts={"test:contains_a_bet": "maybe"},
                trap_hints=["trap:nope"],
            ),
        )
        self.assertEqual(len(problems), 3)

    def test_state_round_trips(self):
        state = assess.StrategyState(slots={"slot:wtp_customers": "filled"}, asked=["q:open_what_is_it"])
        self.assertEqual(assess.StrategyState.from_dict(state.as_dict()).as_dict(), state.as_dict())


class TestPrescreen(unittest.TestCase):
    def test_flags_plan_shaped_text(self):
        text = "Phase 1: launch the new portal by end of FY26. Workstream owners assigned."
        traps = {h["trap"] for h in assess.prescreen(text)}
        self.assertIn("trap:plan_as_strategy", traps)

    def test_flags_vague_language(self):
        traps = {h["trap"] for h in assess.prescreen("We will be a world-class, customer-centric partner.")}
        self.assertIn("trap:vague_language", traps)

    def test_flags_both_routes_claim(self):
        traps = {h["trap"] for h in assess.prescreen("We offer the best quality at the best price.")}
        self.assertIn("trap:stuck_in_the_middle", traps)

    def test_hints_are_marked_unverified(self):
        for hint in assess.prescreen("Our moat is unassailable."):
            self.assertIn("unverified", hint["status"])

    def test_clean_text_is_quiet(self):
        text = "Distributors control the reorder decision, so we win only if they earn more per shelf metre."
        self.assertEqual(assess.prescreen(text), [])

    def test_every_hint_names_a_real_trap(self):
        for _trap_id, pattern, _note in assess._PRESCREEN:
            re.compile(pattern)  # must compile
        for trap_id, _pattern, _note in assess._PRESCREEN:
            self.assertEqual(GRAPH.node(trap_id)["type"], "trap")


class TestInterview(unittest.TestCase):
    def test_fresh_session_opens_with_an_opener(self):
        asks = interview.next_questions(GRAPH, assess.StrategyState(), limit=2)
        self.assertTrue(asks)
        self.assertIn("opening", GRAPH.node(asks[0]["id"])["ask_when"])

    def test_blocking_failure_dominates_the_queue(self):
        state = assess.StrategyState(
            verdicts={"test:contains_a_bet": "fail"}, asked=["q:open_what_is_it"]
        )
        asks = interview.next_questions(GRAPH, state, limit=3)
        self.assertIn("test:contains_a_bet", asks[0]["probes"])
        self.assertEqual(asks[0]["reason"], "a blocking test has failed")

    def test_asked_questions_are_not_repeated(self):
        state = assess.StrategyState()
        for _ in range(12):
            asks = interview.next_questions(GRAPH, state, limit=1)
            if not asks:
                break
            self.assertNotIn(asks[0]["id"], state.asked)
            state.asked.append(asks[0]["id"])
        self.assertEqual(len(state.asked), len(set(state.asked)))

    def test_slot_dependencies_are_respected(self):
        """A dependent slot is not asked about while its prerequisite is empty."""
        state = assess.StrategyState(asked=["q:open_what_is_it"])
        asks = interview.next_questions(GRAPH, state, limit=25)
        offered = {c for a in asks for c in a["covers"]}
        # wtp_exclusions depends on wtp_customers, which is still empty
        if "slot:wtp_exclusions" in offered:
            self.assertIn("slot:wtp_customers", offered)

    def test_every_question_carries_its_justification(self):
        asks = interview.next_questions(GRAPH, assess.StrategyState(), limit=5)
        for ask in asks:
            self.assertTrue(ask["reason"])
            self.assertTrue(ask["because"])

    def test_policy_is_deterministic(self):
        state = assess.StrategyState(
            verdicts={"test:htw_single_logic": "fail", "test:wtp_has_exclusions": "partial"},
            trap_hints=["trap:initiative_list"],
            asked=["q:open_what_is_it"],
        )
        first = interview.next_questions(GRAPH, state, limit=5)
        second = interview.next_questions(GRAPH, state, limit=5)
        self.assertEqual([q["id"] for q in first], [q["id"] for q in second])

    def test_trap_hints_pull_in_detecting_questions(self):
        """A hinted trap surfaces once the higher-priority work is done.

        The policy deliberately ranks missing required slots above suspected
        traps, so with an empty state the queue is legitimately full of slot
        questions. Fill the slots and the trap hint must then come through.
        """
        state = assess.StrategyState(
            slots={s["id"]: "filled" for s in GRAPH.by_type("slot")},
            trap_hints=["trap:misplaced_shoulds"],
            asked=["q:open_what_is_it"],
        )
        asks = interview.next_questions(GRAPH, state, limit=20)
        detected = {t for a in asks for t in a["detects"]}
        self.assertIn("trap:misplaced_shoulds", detected)

    def test_trap_hints_are_not_starved_forever(self):
        """With slots filled, a hinted trap must outrank generic breadth questions."""
        state = assess.StrategyState(
            slots={s["id"]: "filled" for s in GRAPH.by_type("slot")},
            trap_hints=["trap:execution_alibi"],
            asked=["q:open_what_is_it"],
        )
        asks = interview.next_questions(GRAPH, state, limit=5)
        reasons = {a["reason"] for a in asks}
        self.assertIn("a suspected pattern needs confirming", reasons)

    def test_session_plan_does_not_mutate_state(self):
        state = assess.StrategyState()
        before = json.dumps(state.as_dict(), sort_keys=True)
        interview.session_plan(GRAPH, state, rounds=3)
        self.assertEqual(json.dumps(state.as_dict(), sort_keys=True), before)

    def test_session_plan_advances(self):
        plan = interview.session_plan(GRAPH, assess.StrategyState(), rounds=4, per_round=2)
        self.assertGreaterEqual(len(plan), 2)
        seen = [q["id"] for r in plan for q in r["questions"]]
        self.assertEqual(len(seen), len(set(seen)), "the plan repeats a question")

    def test_coverage_report_counts_asked(self):
        state = assess.StrategyState(asked=["q:logic_wwhtbt"])
        report = interview.coverage_report(GRAPH, state)
        logic = next(r for r in report["by_pillar"] if r["pillar"] == "pillar:logic")
        self.assertEqual(logic["asked"], 1)
        self.assertEqual(report["asked_total"], 1)

    def test_queue_eventually_drains(self):
        state = assess.StrategyState(verdicts={t["id"]: "pass" for t in GRAPH.by_type("test")})
        state.slots = {s["id"]: "filled" for s in GRAPH.by_type("slot")}
        for _ in range(200):
            asks = interview.next_questions(GRAPH, state, limit=1)
            if not asks:
                break
            state.asked.append(asks[0]["id"])
        else:
            self.fail("question queue never drained")


class TestQuery(unittest.TestCase):
    def test_search_finds_a_known_concept(self):
        hits = query.search(GRAPH, "where-to-play")
        self.assertIn("concept:where_to_play", [h["id"] for h in hits])

    def test_search_respects_type_filter(self):
        hits = query.search(GRAPH, "customer", types=("question",))
        self.assertTrue(hits)
        self.assertTrue(all(h["type"] == "question" for h in hits))

    def test_pillar_pack_is_complete(self):
        pack = query.pillar_pack(GRAPH, "pillar:how_to_win")
        for key in ("concepts", "principles", "traps", "tests", "questions"):
            self.assertTrue(pack[key], f"pillar pack missing {key}")

    def test_pillar_pack_orders_tests_by_severity(self):
        tests = query.pillar_pack(GRAPH, "pillar:definition")["tests"]
        ranks = [{"blocking": 3, "major": 2, "minor": 1}[t["severity"]] for t in tests]
        self.assertEqual(ranks, sorted(ranks, reverse=True))

    def test_citations_resolve_to_urls(self):
        cites = query.citations(GRAPH, "concept:wwhtbt")
        self.assertTrue(cites)
        for cite in cites:
            self.assertTrue(cite["url"].startswith("https://"))
            self.assertTrue(cite["title"])

    def test_explain_finds_a_path(self):
        result = query.explain(GRAPH, "concept:where_to_play", "trap:everything_to_everyone")
        self.assertTrue(result["path"])
        self.assertLessEqual(len(result["path"]), 7)

    def test_trap_pack_names_the_principle_violated(self):
        pack = query.trap_pack(GRAPH, "trap:plan_as_strategy")
        self.assertTrue(pack["violates"])
        self.assertTrue(pack["caught_by"])

    def test_corpus_is_sorted_and_annotated(self):
        rows = query.corpus(GRAPH)
        self.assertTrue(rows)
        self.assertTrue(any(r["cited_by"] > 0 for r in rows))


class TestBuild(unittest.TestCase):
    def test_build_writes_all_three_artefacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            result = build.build(out_dir=out)
            self.assertEqual(result["errors"], [])
            for name in ("graph.sqlite", "graph.json", "graph.cypher"):
                self.assertTrue((out / name).exists(), name)

            conn = sqlite3.connect(out / "graph.sqlite")
            try:
                nodes = conn.execute("SELECT count(*) FROM node").fetchone()[0]
                edges = conn.execute("SELECT count(*) FROM edge").fetchone()[0]
                self.assertEqual(nodes, len(GRAPH))
                self.assertGreater(edges, 500)
                row = conn.execute("SELECT payload FROM node WHERE id = 'test:contains_a_bet'").fetchone()
                self.assertEqual(json.loads(row[0])["severity"], "blocking")
                # payloads must not leak internal bookkeeping fields
                self.assertNotIn("_file", json.loads(row[0]))
            finally:
                conn.close()

    def test_json_export_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = build.write_json(GRAPH, Path(tmp) / "graph.json")
            doc = json.loads(path.read_text())
            self.assertEqual(len(doc["nodes"]), len(GRAPH))
            self.assertEqual(doc["meta"]["node_total"], len(GRAPH))

    def test_cypher_escapes_quotes(self):
        with tempfile.TemporaryDirectory() as tmp:
            text = (build.write_cypher(GRAPH, Path(tmp) / "g.cypher")).read_text()
            self.assertIn("CREATE CONSTRAINT", text)
            for line in text.splitlines():
                if line.startswith("CREATE (:GraphifyNode"):
                    self.assertTrue(line.endswith(");"), line[:80])


if __name__ == "__main__":
    unittest.main()
