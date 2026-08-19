"""Retrieval over the graph. This is the surface the agent calls."""

from __future__ import annotations

from typing import Any

from .model import Graph, load_graph


def _brief(node: dict[str, Any]) -> dict[str, Any]:
    """A compact view of a node, suitable for dropping into a prompt."""
    out: dict[str, Any] = {"id": node["id"], "type": node["type"]}
    for key in ("label", "text", "summary", "statement", "intent", "why_it_matters", "severity", "kind", "depth"):
        if node.get(key):
            out[key] = node[key]
    return out


def citations(graph: Graph, node_id: str) -> list[dict[str, str]]:
    """The published pieces behind a node, as title + url."""
    return [
        {"title": s.get("label", ""), "url": s.get("url", "")}
        for s in graph.targets(node_id, "CITES")
    ]


def search(graph: Graph, term: str, limit: int = 12, types: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
    """Substring search across the human-readable fields of every node."""
    needle = term.lower().strip()
    if not needle:
        return []
    scored: list[tuple[int, dict[str, Any]]] = []
    for node in graph.nodes.values():
        if types and node["type"] not in types:
            continue
        haystacks = [
            (str(node.get("label", "")), 6),
            (" ".join(node.get("aka", []) or []), 5),
            (str(node.get("text", "")), 4),
            (str(node.get("summary", "")), 3),
            (str(node.get("statement", "")), 3),
            (str(node.get("practitioner_note", "")), 2),
            (str(node.get("why_it_matters", "")), 2),
            (str(node.get("intent", "")), 2),
        ]
        score = sum(weight for text, weight in haystacks if needle in text.lower())
        if score:
            scored.append((score, node))
    scored.sort(key=lambda pair: (-pair[0], pair[1]["id"]))
    return [_brief(n) for _, n in scored[:limit]]


def concept_pack(graph: Graph, concept_id: str) -> dict[str, Any]:
    """Everything the agent needs in order to reason about one concept."""
    node = graph.node(concept_id)
    return {
        "concept": _brief(node) | {"practitioner_note": node.get("practitioner_note", "")},
        "pillar": node.get("pillar"),
        "part_of": [_brief(n) for n in graph.targets(concept_id, "PART_OF")],
        "related": [_brief(n) for n in graph.targets(concept_id, "RELATED_TO")],
        "tested_by": [_brief(n) for n in graph.sources_of(concept_id, "EVALUATES")],
        "traps": [_brief(n) for n in graph.sources_of(concept_id, "CONFUSED_WITH")],
        "citations": citations(graph, concept_id),
    }


def pillar_pack(graph: Graph, pillar_id: str) -> dict[str, Any]:
    """The full assessment kit for one area of strategy."""
    pillar = graph.node(pillar_id)
    in_pillar = [n for n in graph.sources_of(pillar_id, "IN_PILLAR")]
    of = lambda t: sorted((n for n in in_pillar if n["type"] == t), key=lambda n: n["id"])  # noqa: E731
    tests = sorted(
        of("test"),
        key=lambda n: (-{"blocking": 3, "major": 2, "minor": 1}[n["severity"]], -n["weight"], n["id"]),
    )
    return {
        "pillar": {
            "id": pillar["id"],
            "label": pillar["label"],
            "summary": pillar["summary"],
            "assess_focus": pillar.get("assess_focus", ""),
            "order": pillar.get("order"),
        },
        "concepts": [_brief(n) for n in of("concept")],
        "principles": [_brief(n) for n in of("principle")],
        "traps": [
            _brief(n) | {"signals": n.get("signals", []), "coaching_move": n.get("coaching_move", "")}
            for n in of("trap")
        ],
        "tests": [
            _brief(n)
            | {
                "statement": n["statement"],
                "pass_signals": n["pass_signals"],
                "fail_signals": n["fail_signals"],
                "weight": n["weight"],
            }
            for n in tests
        ],
        "slots": [_brief(n) | {"required": n.get("required", False)} for n in sorted(of("slot"), key=lambda n: n["order"])],
        "questions": [
            _brief(n) | {"ask_when": n.get("ask_when", []), "probes": n.get("probes", [])}
            for n in sorted(of("question"), key=lambda n: (n["depth"], n["id"]))
        ],
    }


def test_pack(graph: Graph, test_id: str) -> dict[str, Any]:
    node = graph.node(test_id)
    return {
        "test": _brief(node)
        | {
            "statement": node["statement"],
            "pass_signals": node["pass_signals"],
            "fail_signals": node["fail_signals"],
            "weight": node["weight"],
        },
        "questions": [_brief(n) for n in graph.sources_of(test_id, "PROBES")],
        "traps": [_brief(n) for n in graph.targets(test_id, "DETECTS")],
        "concepts": [_brief(n) for n in graph.targets(test_id, "EVALUATES")],
        "slots": [_brief(n) for n in graph.targets(test_id, "APPLIES_TO")],
        "gates": [e.dst for e in graph.out_edges(test_id, "GATES")],
        "citations": citations(graph, test_id),
    }


def trap_pack(graph: Graph, trap_id: str) -> dict[str, Any]:
    node = graph.node(trap_id)
    return {
        "trap": _brief(node)
        | {
            "signals": node.get("signals", []),
            "why_costly": node.get("why_costly", ""),
            "coaching_move": node.get("coaching_move", ""),
        },
        "caught_by": [_brief(n) for n in graph.targets(trap_id, "MITIGATED_BY")],
        "questions": [_brief(n) for n in graph.sources_of(trap_id, "DETECTS") if n["type"] == "question"],
        "violates": [_brief(n) for n in graph.targets(trap_id, "VIOLATES")],
        "citations": citations(graph, trap_id),
    }


def questions_for_slot(graph: Graph, slot_id: str) -> list[dict[str, Any]]:
    qs = [n for n in graph.sources_of(slot_id, "COVERS") if n["type"] == "question"]
    return [_brief(n) for n in sorted(qs, key=lambda n: (n["depth"], n["id"]))]


def follow_ups(graph: Graph, question_id: str) -> list[dict[str, Any]]:
    return [_brief(n) for n in graph.targets(question_id, "FOLLOW_UP")]


def explain(graph: Graph, node_id: str, other_id: str) -> dict[str, Any]:
    """Why two things in the graph are connected - used to justify a question."""
    trail = graph.path(node_id, other_id)
    return {
        "path": trail,
        "steps": [
            {"id": nid, "type": graph.node(nid)["type"], "label": graph.node(nid).get("label", "")}
            for nid in trail
        ],
    }


def corpus(graph: Graph) -> list[dict[str, Any]]:
    """The indexed source material, newest first where a date is known."""
    rows = [
        {
            "id": s["id"],
            "title": s.get("label", ""),
            "url": s.get("url", ""),
            "published": s.get("published", ""),
            "kind": s.get("kind", ""),
            "themes": s.get("themes", []),
            "cited_by": len(graph.in_edges(s["id"], "CITES")),
        }
        for s in graph.by_type("source")
    ]
    return sorted(rows, key=lambda r: (r["published"] or "0000", r["id"]), reverse=True)


def open_graph() -> Graph:
    return load_graph()
