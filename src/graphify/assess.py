"""Assessment: turn a strategy's state into per-pillar readiness and a gap list.

Division of labour, deliberately:

* The **graph** decides which tests apply, how much each one counts, what gates
  what, and which questions follow from a gap. That part is deterministic and
  auditable.
* The **agent** supplies the verdicts. Judging whether a stated way of winning
  really resolves to a cost advantage is a reading task, not a keyword task, so
  the code never guesses it.

``prescreen`` exists only to point the agent at passages worth reading closely.
Its output is explicitly labelled as unverified and never becomes a verdict.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from .model import SEVERITIES, Graph

VERDICTS = ("pass", "partial", "fail", "unknown")
VERDICT_CREDIT = {"pass": 1.0, "partial": 0.5, "fail": 0.0, "unknown": 0.0}
SLOT_STATES = ("filled", "partial", "empty")


@dataclass
class StrategyState:
    """What the agent currently knows about the user's strategy."""

    slots: dict[str, str] = field(default_factory=dict)  # slot_id -> filled|partial|empty
    verdicts: dict[str, str] = field(default_factory=dict)  # test_id -> pass|partial|fail|unknown
    evidence: dict[str, str] = field(default_factory=dict)  # test_id -> why that verdict
    trap_hints: list[str] = field(default_factory=list)  # trap ids suspected, not confirmed
    asked: list[str] = field(default_factory=list)  # question ids already put to the user

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "StrategyState":
        return cls(
            slots=dict(raw.get("slots", {})),
            verdicts=dict(raw.get("verdicts", {})),
            evidence=dict(raw.get("evidence", {})),
            trap_hints=list(raw.get("trap_hints", [])),
            asked=list(raw.get("asked", [])),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "slots": self.slots,
            "verdicts": self.verdicts,
            "evidence": self.evidence,
            "trap_hints": self.trap_hints,
            "asked": self.asked,
        }

    def slot_state(self, slot_id: str) -> str:
        return self.slots.get(slot_id, "empty")

    def verdict(self, test_id: str) -> str:
        return self.verdicts.get(test_id, "unknown")


def validate_state(graph: Graph, state: StrategyState) -> list[str]:
    problems = []
    for slot_id, value in state.slots.items():
        if slot_id not in graph.nodes or graph.nodes[slot_id]["type"] != "slot":
            problems.append(f"unknown slot {slot_id!r}")
        elif value not in SLOT_STATES:
            problems.append(f"slot {slot_id}: state must be one of {SLOT_STATES}")
    for test_id, value in state.verdicts.items():
        if test_id not in graph.nodes or graph.nodes[test_id]["type"] != "test":
            problems.append(f"unknown test {test_id!r}")
        elif value not in VERDICTS:
            problems.append(f"test {test_id}: verdict must be one of {VERDICTS}")
    for trap_id in state.trap_hints:
        if trap_id not in graph.nodes or graph.nodes[trap_id]["type"] != "trap":
            problems.append(f"unknown trap {trap_id!r}")
    for qid in state.asked:
        if qid not in graph.nodes or graph.nodes[qid]["type"] != "question":
            problems.append(f"unknown question {qid!r}")
    return problems


# ---------------------------------------------------------------- prescreen

# Each pattern is a *hint to read closely*, never a finding. Tuned to be cheap
# and obvious; the agent confirms or discards every one of them.
_PRESCREEN = (
    (
        "trap:vague_language",
        r"\b(world[- ]class|best[- ]in[- ]class|customer[- ]centric|cutting[- ]edge|"
        r"industry[- ]leading|synergies|excellence|innovative culture)\b",
        "Language that would survive in any competitor's document.",
    ),
    (
        "trap:financial_targets_only",
        r"\b(grow revenue by|\d+\s?% (growth|margin|cagr)|double (revenue|ebitda)|"
        r"reach \$?\d+(\.\d+)?\s?(m|bn|billion|million))\b",
        "A financial target may be standing in for a definition of winning.",
    ),
    (
        "trap:initiative_list",
        r"(?m)^\s*(\d+[\.\)]|[-*•])\s+(launch|build|improve|expand|invest|"
        r"accelerate|optimi[sz]e|roll out|implement|drive)\b",
        "Reads like a programme list; check whether a single winning logic connects them.",
    ),
    (
        "trap:misplaced_shoulds",
        r"\b(customers should|the market (will|should) (recognise|recognize|realise|realize|reward)|"
        r"partners should|should value|will naturally)\b",
        "An assumption about someone else's behaviour stated as an obligation.",
    ),
    (
        "trap:stuck_in_the_middle",
        r"\b(best quality at the (best|lowest) price|premium .{0,24}(and|while) .{0,24}(low[- ]cost|lowest cost)|"
        r"both differentiated and low[- ]cost)\b",
        "Claims both routes to advantage; look for the trade-offs.",
    ),
    (
        "trap:everything_to_everyone",
        r"\b(all (customers|segments|markets)|any (customer|organisation|organization) (that|who)|"
        r"total addressable market|anyone who needs)\b",
        "Arena may not exclude anything.",
    ),
    (
        "trap:demographic_segments",
        r"\b(enterprise, mid[- ]market|smb|companies with (over|more than) \d+|"
        r"aged \d+[-–]\d+|by (region|vertical|headcount|revenue band))\b",
        "Segments may be descriptive rather than behavioural.",
    ),
    (
        "trap:moat_thinking",
        r"\b(moat|defensible barrier|first[- ]mover advantage|lock[- ]in|unassailable)\b",
        "Advantage may be treated as static rather than renewed.",
    ),
    (
        "trap:faux_science",
        r"\b(\d{4}\s?[-–]\s?\d{4} forecast|five[- ]year projection|"
        r"npv of \$?\d|monte carlo|regression (shows|indicates))\b",
        "Quantification may be doing work the data cannot support.",
    ),
    (
        "trap:plan_as_strategy",
        r"\b(q[1-4] \d{4}|phase [1-3]|milestone|workstream|gantt|by end of (fy)?\d{2,4})\b",
        "Structured as a delivery plan; check whether any bet on outside behaviour exists.",
    ),
)


def prescreen(text: str) -> list[dict[str, str]]:
    """Cheap textual hints for the agent to verify. Not findings."""
    hints: list[dict[str, str]] = []
    for trap_id, pattern, note in _PRESCREEN:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            hints.append(
                {
                    "trap": trap_id,
                    "matched": match.group(0)[:80],
                    "note": note,
                    "status": "unverified - confirm by reading the passage",
                }
            )
    return hints


# ---------------------------------------------------------------- scoring


def _tests_for_pillar(graph: Graph, pillar_id: str) -> list[dict[str, Any]]:
    return [n for n in graph.sources_of(pillar_id, "IN_PILLAR") if n["type"] == "test"]


def assess(graph: Graph, state: StrategyState) -> dict[str, Any]:
    """Per-pillar readiness, blocking failures, gaps and trap findings."""
    pillars = []
    blocking: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []

    for pillar in graph.pillars_in_order():
        tests = _tests_for_pillar(graph, pillar["id"])
        earned = possible = 0.0
        assessed = 0
        for test in tests:
            verdict = state.verdict(test["id"])
            weight = float(test["weight"])
            possible += weight
            earned += weight * VERDICT_CREDIT[verdict]
            if verdict != "unknown":
                assessed += 1
            if verdict in ("fail", "partial"):
                entry = {
                    "test": test["id"],
                    "label": test["label"],
                    "pillar": pillar["id"],
                    "verdict": verdict,
                    "severity": test["severity"],
                    "weight": test["weight"],
                    "statement": test["statement"],
                    "why_it_matters": test["why_it_matters"],
                    "evidence": state.evidence.get(test["id"], ""),
                    "priority": SEVERITIES[test["severity"]] * test["weight"] * (2 if verdict == "fail" else 1),
                }
                gaps.append(entry)
                if test["severity"] == "blocking" and verdict == "fail":
                    blocking.append(entry)

        required = [
            s
            for s in graph.sources_of(pillar["id"], "IN_PILLAR")
            if s["type"] == "slot" and s.get("required")
        ]
        missing = [s["id"] for s in required if state.slot_state(s["id"]) == "empty"]

        pillars.append(
            {
                "pillar": pillar["id"],
                "label": pillar["label"],
                "order": pillar.get("order"),
                "readiness": round(earned / possible, 3) if possible else None,
                "coverage": round(assessed / len(tests), 3) if tests else None,
                "tests_total": len(tests),
                "tests_assessed": assessed,
                "missing_required_slots": missing,
            }
        )

    gaps.sort(key=lambda g: (-g["priority"], g["test"]))

    scored = [p for p in pillars if p["readiness"] is not None]
    overall = round(sum(p["readiness"] for p in scored) / len(scored), 3) if scored else None
    covered = [p for p in pillars if p["coverage"] is not None]
    coverage = round(sum(p["coverage"] for p in covered) / len(covered), 3) if covered else None

    return {
        "overall_readiness": overall,
        "assessment_coverage": coverage,
        "blocking": blocking,
        "gaps": gaps,
        "pillars": pillars,
        "traps_suspected": [
            {
                "trap": graph.node(t)["id"],
                "label": graph.node(t)["label"],
                "signals": graph.node(t).get("signals", []),
                "caught_by": graph.node(t).get("mitigated_by", []),
            }
            for t in dict.fromkeys(state.trap_hints)
            if t in graph.nodes
        ],
        "gated": gated_pillars(graph, state),
        "note": (
            "Readiness is a coverage-weighted view of the tests the agent has actually judged. "
            "It is a conversation aid, not a score of the strategy's quality."
        ),
    }


def gated_pillars(graph: Graph, state: StrategyState) -> list[dict[str, Any]]:
    """Areas not worth assessing yet because an upstream blocking test failed."""
    out = []
    for edge in (e for e in graph.edges if e.type == "GATES"):
        verdict = state.verdict(edge.src)
        if verdict in ("fail", "unknown"):
            out.append(
                {
                    "pillar": edge.dst,
                    "blocked_by": edge.src,
                    "verdict": verdict,
                    "why": edge.note,
                }
            )
    return out


def readiness_summary(report: dict[str, Any]) -> str:
    """A short plain-text digest, for logs and CLI output."""
    lines = []
    overall = report["overall_readiness"]
    lines.append(f"overall readiness: {overall if overall is not None else 'n/a'}   coverage: {report['assessment_coverage']}")
    if report["blocking"]:
        lines.append("blocking:")
        lines.extend(f"  ! {g['label']} ({g['test']})" for g in report["blocking"])
    lines.append("weakest areas:")
    for pillar in sorted(
        (p for p in report["pillars"] if p["readiness"] is not None), key=lambda p: p["readiness"]
    )[:4]:
        lines.append(f"  {pillar['readiness']:.2f}  {pillar['label']}")
    return "\n".join(lines)


def iter_gap_tests(report: dict[str, Any]) -> Iterable[str]:
    return (g["test"] for g in report["gaps"])
