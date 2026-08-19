"""Question selection: decide what to ask next, and say why.

The policy is deterministic so that two runs over the same state produce the
same queue, and so that every question the agent asks can be traced to a gap in
the graph rather than to improvisation.

Priority order:

1. A failed blocking test - nothing downstream is worth discussing yet.
2. A required slot that is still empty, in cascade order, provided its
   prerequisites are filled.
3. A failed or partial test, ranked by severity x weight.
4. A suspected trap that no answered question has yet resolved.
5. Depth: follow-ups on ground already opened.
6. Breadth: the earliest pillar with no coverage at all.
"""

from __future__ import annotations

from typing import Any

from .assess import StrategyState, assess
from .model import SEVERITIES, Graph

REASONS = {
    "blocking": "a blocking test has failed",
    "slot": "a required element of the strategy is missing",
    "gap": "a test came back weak",
    "trap": "a suspected pattern needs confirming",
    "depth": "the previous answer opened something worth pushing on",
    "breadth": "this area has not been looked at yet",
    "opening": "opening the conversation",
    "closing": "closing the conversation",
}


def _questions(graph: Graph) -> list[dict[str, Any]]:
    return graph.by_type("question")


def _for_test(graph: Graph, test_id: str) -> list[dict[str, Any]]:
    return [n for n in graph.sources_of(test_id, "PROBES") if n["type"] == "question"]


def _for_slot(graph: Graph, slot_id: str) -> list[dict[str, Any]]:
    return [n for n in graph.sources_of(slot_id, "COVERS") if n["type"] == "question"]


def _for_trap(graph: Graph, trap_id: str) -> list[dict[str, Any]]:
    return [n for n in graph.sources_of(trap_id, "DETECTS") if n["type"] == "question"]


def _slot_ready(graph: Graph, slot: dict[str, Any], state: StrategyState) -> bool:
    """A slot is worth asking about once anything it depends on is at least partial."""
    for dep in slot.get("depends_on", []) or []:
        if state.slot_state(dep) == "empty":
            return False
    return True


def _candidate(
    question: dict[str, Any], reason_key: str, score: float, because: str
) -> dict[str, Any]:
    return {
        "id": question["id"],
        "text": question["text"],
        "kind": question["kind"],
        "depth": question["depth"],
        "pillar": question["pillar"],
        "intent": question["intent"],
        "reason": REASONS[reason_key],
        "because": because,
        "score": round(score, 3),
        "probes": question.get("probes", []),
        "covers": question.get("covers", []),
        "detects": question.get("detects", []),
        "follow_ups": question.get("follow_ups", []),
    }


def next_questions(
    graph: Graph,
    state: StrategyState,
    limit: int = 3,
    report: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    report = report or assess(graph, state)
    asked = set(state.asked)
    pillar_order = {p["id"]: p.get("order", 0) for p in graph.pillars_in_order()}
    candidates: dict[str, dict[str, Any]] = {}

    def offer(question: dict[str, Any], reason_key: str, score: float, because: str) -> None:
        if question["id"] in asked:
            return
        existing = candidates.get(question["id"])
        if existing is None or score > existing["score"]:
            candidates[question["id"]] = _candidate(question, reason_key, score, because)

    # 0. nothing asked yet: start with the openers
    if not asked:
        for question in _questions(graph):
            if "opening" in question.get("ask_when", []):
                offer(question, "opening", 1000, "no ground covered yet")

    # 1. failed blocking tests
    for gap in report["blocking"]:
        for question in _for_test(graph, gap["test"]):
            offer(question, "blocking", 900 - question["depth"], f"{gap['test']} failed")

    # 2. missing required slots, in cascade order
    for slot in sorted(
        (s for s in graph.by_type("slot") if s.get("required")), key=lambda s: s["order"]
    ):
        if state.slot_state(slot["id"]) != "empty" or not _slot_ready(graph, slot, state):
            continue
        for question in _for_slot(graph, slot["id"]):
            if "slot_empty" not in question.get("ask_when", []) and "always" not in question.get("ask_when", []):
                continue
            score = 800 - slot["order"] / 10 - question["depth"]
            offer(question, "slot", score, f"{slot['id']} is empty")

    # 3. weak tests
    for gap in report["gaps"]:
        if gap in report["blocking"]:
            continue
        want = "test_fail" if gap["verdict"] == "fail" else "test_partial"
        for question in _for_test(graph, gap["test"]):
            allowed = question.get("ask_when", [])
            if want not in allowed and "always" not in allowed:
                continue
            score = 500 + gap["priority"] - question["depth"] * 2
            offer(question, "gap", score, f"{gap['test']} came back {gap['verdict']}")

    # 4. suspected traps
    for trap in report["traps_suspected"]:
        for question in _for_trap(graph, trap["trap"]):
            allowed = question.get("ask_when", [])
            if "trap_hint" not in allowed and "always" not in allowed:
                continue
            offer(question, "trap", 400 - question["depth"], f"{trap['trap']} suspected")

    # 5. depth: follow-ups from what has already been asked
    for qid in state.asked:
        node = graph.get(qid)
        if not node:
            continue
        for follow in graph.targets(qid, "FOLLOW_UP"):
            offer(follow, "depth", 300 - follow["depth"], f"follows {qid}")

    # 6. breadth: earliest pillar with no coverage
    for pillar in report["pillars"]:
        if pillar["tests_assessed"]:
            continue
        for question in _questions(graph):
            if question["pillar"] != pillar["pillar"] or question["depth"] > 1:
                continue
            score = 200 - pillar_order.get(pillar["pillar"], 0) / 10
            offer(question, "breadth", score, f"{pillar['pillar']} not yet examined")

    ranked = sorted(
        candidates.values(),
        key=lambda c: (-c["score"], pillar_order.get(c["pillar"], 99), c["id"]),
    )
    return ranked[:limit]


def closing_questions(graph: Graph, state: StrategyState) -> list[dict[str, Any]]:
    asked = set(state.asked)
    return [
        _candidate(q, "closing", 0, "wrapping up")
        for q in _questions(graph)
        if "closing" in q.get("ask_when", []) and q["id"] not in asked
    ]


def session_plan(graph: Graph, state: StrategyState, rounds: int = 5, per_round: int = 3) -> list[dict[str, Any]]:
    """Preview the line of questioning, assuming each question gets answered.

    Purely for inspecting the policy - it does not change any state. Answers are
    optimistically assumed to fill the slots a question covers, which is why this
    is a preview rather than a script.
    """
    preview: list[dict[str, Any]] = []
    working = StrategyState.from_dict(state.as_dict())
    for round_no in range(1, rounds + 1):
        batch = next_questions(graph, working, limit=per_round)
        if not batch:
            break
        preview.append({"round": round_no, "questions": batch})
        for question in batch:
            working.asked.append(question["id"])
            for slot_id in question["covers"]:
                working.slots.setdefault(slot_id, "partial")
    return preview


def coverage_report(graph: Graph, state: StrategyState) -> dict[str, Any]:
    """What has been asked, what remains, by pillar."""
    asked = set(state.asked)
    rows = []
    for pillar in graph.pillars_in_order():
        questions = [q for q in _questions(graph) if q["pillar"] == pillar["id"]]
        rows.append(
            {
                "pillar": pillar["id"],
                "label": pillar["label"],
                "asked": sum(1 for q in questions if q["id"] in asked),
                "available": len(questions),
            }
        )
    return {"by_pillar": rows, "asked_total": len(asked), "questions_total": len(_questions(graph))}
