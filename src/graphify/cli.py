"""Command line interface.

    python -m graphify build            build sqlite/json/cypher artefacts
    python -m graphify validate         integrity check the data files
    python -m graphify stats            node and edge counts
    python -m graphify show <id>        one node, with its neighbourhood
    python -m graphify search <term>    substring search
    python -m graphify pillar <id>      the assessment kit for one pillar
    python -m graphify corpus           the indexed source material
    python -m graphify prescreen <file> textual hints for the agent to verify
    python -m graphify assess <state>   readiness report from a state file
    python -m graphify next <state>     the next questions, with reasons
    python -m graphify plan <state>     preview several rounds of questioning
    python -m graphify agent-context    the bundle an agent loads at session start
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import assess as assess_mod
from . import build as build_mod
from . import interview, query
from .model import load_graph, stats, validate


def _out(payload: Any) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def _load_state(path: str) -> assess_mod.StrategyState:
    raw = json.loads(Path(path).read_text(encoding="utf-8")) if path != "-" else json.load(sys.stdin)
    return assess_mod.StrategyState.from_dict(raw)


def agent_context(graph) -> dict[str, Any]:
    """What an agent loads once, at the start of a session."""
    return {
        "pillars": [
            {
                "id": p["id"],
                "label": p["label"],
                "order": p.get("order"),
                "summary": p["summary"],
                "assess_focus": p.get("assess_focus", ""),
            }
            for p in graph.pillars_in_order()
        ],
        "principles": [
            {"id": n["id"], "statement": n["statement"], "coaching_use": n.get("coaching_use", "")}
            for n in graph.by_type("principle")
        ],
        "traps": [
            {"id": n["id"], "label": n["label"], "signals": n.get("signals", [])}
            for n in graph.by_type("trap")
        ],
        "tests": [
            {
                "id": n["id"],
                "pillar": n["pillar"],
                "label": n["label"],
                "statement": n["statement"],
                "severity": n["severity"],
                "weight": n["weight"],
                "pass_signals": n["pass_signals"],
                "fail_signals": n["fail_signals"],
            }
            for n in graph.by_type("test")
        ],
        "slots": [
            {
                "id": n["id"],
                "pillar": n["pillar"],
                "label": n["label"],
                "order": n["order"],
                "required": n.get("required", False),
                "captures": n.get("captures", ""),
                "sufficient_when": n.get("sufficient_when", ""),
            }
            for n in sorted(graph.by_type("slot"), key=lambda s: s["order"])
        ],
        "counts": stats(graph),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="graphify", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("build")
    sub.add_parser("validate")
    sub.add_parser("stats")
    sub.add_parser("corpus")
    sub.add_parser("agent-context")

    p_show = sub.add_parser("show")
    p_show.add_argument("node_id")

    p_search = sub.add_parser("search")
    p_search.add_argument("term")
    p_search.add_argument("--type", dest="types", action="append")
    p_search.add_argument("--limit", type=int, default=12)

    p_pillar = sub.add_parser("pillar")
    p_pillar.add_argument("pillar_id")

    p_pre = sub.add_parser("prescreen")
    p_pre.add_argument("file")

    for name in ("assess", "next", "plan"):
        p = sub.add_parser(name)
        p.add_argument("state", nargs="?", default="-")
        if name == "next":
            p.add_argument("--limit", type=int, default=3)
        if name == "plan":
            p.add_argument("--rounds", type=int, default=5)

    args = parser.parse_args(argv)

    if args.command == "build":
        result = build_mod.build()
        _out(result)
        return 0

    graph = load_graph()

    if args.command == "validate":
        errors = validate(graph)
        if errors:
            print(f"{len(errors)} problem(s):", file=sys.stderr)
            for err in errors:
                print(f"  {err}", file=sys.stderr)
            return 1
        print(f"ok: {len(graph)} nodes, {len(graph.edges)} edges, no integrity problems")
        return 0

    if args.command == "stats":
        _out(stats(graph))
        return 0

    if args.command == "corpus":
        _out(query.corpus(graph))
        return 0

    if args.command == "agent-context":
        _out(agent_context(graph))
        return 0

    if args.command == "show":
        node = graph.get(args.node_id)
        if node is None:
            print(f"no such node: {args.node_id}", file=sys.stderr)
            return 1
        kind = node["type"]
        if kind == "concept":
            _out(query.concept_pack(graph, node["id"]))
        elif kind == "test":
            _out(query.test_pack(graph, node["id"]))
        elif kind == "trap":
            _out(query.trap_pack(graph, node["id"]))
        elif kind == "pillar":
            _out(query.pillar_pack(graph, node["id"]))
        else:
            payload = {k: v for k, v in node.items() if not k.startswith("_")}
            payload["citations"] = query.citations(graph, node["id"])
            if kind == "question":
                payload["follow_up_detail"] = query.follow_ups(graph, node["id"])
            _out(payload)
        return 0

    if args.command == "search":
        _out(query.search(graph, args.term, limit=args.limit, types=tuple(args.types) if args.types else None))
        return 0

    if args.command == "pillar":
        if args.pillar_id not in graph.nodes:
            print(f"no such pillar: {args.pillar_id}", file=sys.stderr)
            return 1
        _out(query.pillar_pack(graph, args.pillar_id))
        return 0

    if args.command == "prescreen":
        text = Path(args.file).read_text(encoding="utf-8")
        _out({"hints": assess_mod.prescreen(text)})
        return 0

    state = _load_state(args.state)
    problems = assess_mod.validate_state(graph, state)
    if problems:
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1

    if args.command == "assess":
        report = assess_mod.assess(graph, state)
        _out(report)
        print("\n" + assess_mod.readiness_summary(report), file=sys.stderr)
        return 0

    if args.command == "next":
        _out(interview.next_questions(graph, state, limit=args.limit))
        return 0

    if args.command == "plan":
        _out(interview.session_plan(graph, state, rounds=args.rounds))
        return 0

    parser.error(f"unhandled command {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
