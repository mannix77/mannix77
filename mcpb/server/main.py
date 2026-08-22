#!/usr/bin/env python3
"""strategy_graph_mcp - an MCP server over the strategy practitioner graph.

Transport: stdio, newline-delimited JSON-RPC 2.0.

Written against the standard library only, with no MCP SDK. That is a deliberate
choice rather than a shortcut: this project's whole portability argument rests on
having no dependencies, and a stdio MCP server is a JSON-RPC read/dispatch/write
loop. The result is an .mcpb bundle that installs with nothing to resolve.

Every tool here is read-only. The graph is immutable data; the caller owns the
per-session strategy state and passes it in on each call, so the server holds no
state between requests and two identical calls always agree.

stdout carries protocol frames ONLY. Anything diagnostic goes to stderr — a
single stray print to stdout corrupts the stream and the client drops the server.
"""

from __future__ import annotations

import difflib
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Callable

SERVER_NAME = "strategy-graph"
SERVER_VERSION = "0.1.0"

# Echoed back to the client when it proposes one, so this server does not go stale
# as the spec revs. Used only when the client sends nothing.
FALLBACK_PROTOCOL_VERSION = "2025-06-18"

HERE = Path(__file__).resolve().parent


def _bootstrap_paths() -> Path:
    """Make `graphify` importable and locate the data directory.

    Two layouts have to work: the installed bundle (code and data under
    server/lib/) and a developer checkout (src/ and data/ at the repo root).
    """
    candidates = [
        (HERE / "lib", HERE / "lib" / "data"),                      # bundled
        (HERE.parents[1] / "src", HERE.parents[1] / "data"),        # repo checkout
    ]
    for code_dir, data_dir in candidates:
        if (code_dir / "graphify").is_dir() and data_dir.is_dir():
            sys.path.insert(0, str(code_dir))
            return data_dir

    override = os.environ.get("GRAPHIFY_DATA_DIR")
    if override and Path(override).is_dir():
        return Path(override)

    raise SystemExit(
        "strategy-graph: cannot locate the graphify package and data directory.\n"
        f"Looked under {HERE / 'lib'} and {HERE.parents[1]}.\n"
        "Set GRAPHIFY_DATA_DIR if the data lives elsewhere."
    )


DATA_DIR = _bootstrap_paths()

from graphify import assess as assess_mod  # noqa: E402
from graphify import interview, query  # noqa: E402
from graphify.model import load_graph, stats  # noqa: E402

GRAPH = load_graph(DATA_DIR)


def log(message: str) -> None:
    print(f"[strategy-graph] {message}", file=sys.stderr, flush=True)


# --------------------------------------------------------------- rendering

def _md_value(value: Any, depth: int = 0) -> str:
    pad = "  " * depth
    if isinstance(value, dict):
        lines = []
        for key, inner in value.items():
            if inner in (None, "", [], {}):
                continue
            if isinstance(inner, (dict, list)):
                lines.append(f"{pad}- **{key}**")
                lines.append(_md_value(inner, depth + 1))
            else:
                lines.append(f"{pad}- **{key}**: {inner}")
        return "\n".join(lines)
    if isinstance(value, list):
        return "\n".join(_md_value(item, depth) if isinstance(item, (dict, list)) else f"{pad}- {item}" for item in value)
    return f"{pad}{value}"


def render_markdown(name: str, payload: Any) -> str:
    """Human-readable rendering. Bespoke for the tools an agent reads most."""
    if name == "strategy_assess" and isinstance(payload, dict):
        lines = [
            f"**Overall readiness** {payload.get('overall_readiness')}  ·  "
            f"**coverage** {payload.get('assessment_coverage')}",
            "",
        ]
        if payload.get("blocking"):
            lines.append("**Blocking failures**")
            lines += [f"- {g['label']} (`{g['test']}`)" for g in payload["blocking"]]
            lines.append("")
        gaps = payload.get("gaps", [])[:8]
        if gaps:
            lines.append("**Top gaps**")
            lines += [f"- `{g['test']}` — {g['verdict']} · {g['severity']} · {g['label']}" for g in gaps]
            lines.append("")
        weakest = sorted(
            (p for p in payload.get("pillars", []) if p.get("readiness") is not None),
            key=lambda p: p["readiness"],
        )[:5]
        if weakest:
            lines.append("**Weakest areas**")
            lines += [f"- {p['readiness']:.2f} · {p['label']} (coverage {p['coverage']})" for p in weakest]
        lines.append("")
        lines.append(f"_{payload.get('note', '')}_")
        return "\n".join(lines)

    if name == "strategy_next_questions" and isinstance(payload, list):
        if not payload:
            return "No questions remain for this state."
        blocks = []
        for item in payload:
            blocks.append(
                f"**{item['text']}**\n\n"
                f"- why: {item['reason']} — {item['because']}\n"
                f"- id: `{item['id']}` · kind: {item['kind']} · depth: {item['depth']}\n"
                f"- probes: {', '.join(f'`{p}`' for p in item.get('probes', [])) or '—'}"
            )
        return "\n\n".join(blocks)

    if name == "strategy_prescreen" and isinstance(payload, dict):
        hints = payload.get("hints", [])
        if not hints:
            return "No hints. Nothing in the text matched a known pattern — read it yourself regardless."
        lines = ["**Unverified hints — confirm each by reading the passage.**", ""]
        lines += [f"- `{h['trap']}` matched {h['matched']!r} — {h['note']}" for h in hints]
        return "\n".join(lines)

    return _md_value(payload)


def result(name: str, payload: Any, response_format: str) -> dict[str, Any]:
    text = json.dumps(payload, indent=2, ensure_ascii=False) if response_format == "json" else render_markdown(name, payload)
    out: dict[str, Any] = {"content": [{"type": "text", "text": text}]}
    if isinstance(payload, dict):
        out["structuredContent"] = payload
    return out


def tool_error(message: str) -> dict[str, Any]:
    return {"isError": True, "content": [{"type": "text", "text": message}]}


# --------------------------------------------------------------- helpers

def _state(arguments: dict[str, Any]) -> assess_mod.StrategyState:
    raw = arguments.get("state") or {}
    if not isinstance(raw, dict):
        raise ValueError("`state` must be an object. See the state shape in the tool description.")
    state = assess_mod.StrategyState.from_dict(raw)
    problems = assess_mod.validate_state(GRAPH, state)
    if problems:
        raise ValueError(
            "The state references things that are not in the graph:\n  - "
            + "\n  - ".join(problems)
            + "\n\nCall strategy_load_context to get the valid slot and test ids."
        )
    return state


def _node(node_id: str, expected: str) -> dict[str, Any]:
    node = GRAPH.get(node_id)
    if node is None:
        # difflib rather than the substring search: a typo'd id is usually not a
        # substring of the real one, so substring matching almost never helps.
        candidates = [n["id"] for n in GRAPH.by_type(expected)]
        close = difflib.get_close_matches(node_id, candidates, n=5, cutoff=0.6)
        if not close:
            close = [h["id"] for h in query.search(
                GRAPH, node_id.split(":", 1)[-1].replace("_", " "), limit=5, types=(expected,)
            )]
        suggestion = ("\n\nClosest matches: " + ", ".join(f"`{c}`" for c in close)) if close else (
            f"\n\nUse strategy_search to find a valid {expected} id."
        )
        raise ValueError(f"No node `{node_id}`.{suggestion}")
    if node["type"] != expected:
        raise ValueError(f"`{node_id}` is a {node['type']}, not a {expected}.")
    return node


def _paginate(items: list[Any], limit: int, offset: int) -> dict[str, Any]:
    window = items[offset : offset + limit]
    return {
        "total": len(items),
        "count": len(window),
        "offset": offset,
        "items": window,
        "has_more": offset + limit < len(items),
        "next_offset": offset + limit if offset + limit < len(items) else None,
    }


# --------------------------------------------------------------- tools

STATE_SCHEMA = {
    "type": "object",
    "description": (
        "Per-session record of the user's strategy. The caller owns it; the server never stores it. "
        "Shape: {slots: {slot_id: filled|partial|empty}, verdicts: {test_id: pass|partial|fail|unknown}, "
        "evidence: {test_id: why}, trap_hints: [trap_id], asked: [question_id]}"
    ),
    "properties": {
        "slots": {"type": "object"},
        "verdicts": {"type": "object"},
        "evidence": {"type": "object"},
        "trap_hints": {"type": "array", "items": {"type": "string"}},
        "asked": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": True,
}

FORMAT_SCHEMA = {
    "type": "string",
    "enum": ["markdown", "json"],
    "default": "markdown",
    "description": "markdown for reading, json for programmatic use. Structured data is returned either way.",
}


def t_load_context(a: dict[str, Any]) -> Any:
    return {
        "pillars": [
            {
                "id": p["id"],
                "label": p["label"],
                "order": p.get("order"),
                "summary": p["summary"],
                "assess_focus": p.get("assess_focus", ""),
            }
            for p in GRAPH.pillars_in_order()
        ],
        "principles": [
            {"id": n["id"], "statement": n["statement"], "coaching_use": n.get("coaching_use", "")}
            for n in GRAPH.by_type("principle")
        ],
        "traps": [
            {"id": n["id"], "label": n["label"], "signals": n.get("signals", [])}
            for n in GRAPH.by_type("trap")
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
            for n in GRAPH.by_type("test")
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
            for n in sorted(GRAPH.by_type("slot"), key=lambda s: s["order"])
        ],
        "counts": stats(GRAPH),
    }


def t_search(a: dict[str, Any]) -> Any:
    term = (a.get("term") or "").strip()
    if not term:
        raise ValueError("`term` is required.")
    types = a.get("types")
    return {
        "term": term,
        "results": query.search(
            GRAPH, term, limit=int(a.get("limit", 12)), types=tuple(types) if types else None
        ),
    }


def t_get_pillar(a: dict[str, Any]) -> Any:
    return query.pillar_pack(GRAPH, _node(a["pillar_id"], "pillar")["id"])


def t_get_concept(a: dict[str, Any]) -> Any:
    return query.concept_pack(GRAPH, _node(a["concept_id"], "concept")["id"])


def t_get_test(a: dict[str, Any]) -> Any:
    return query.test_pack(GRAPH, _node(a["test_id"], "test")["id"])


def t_get_trap(a: dict[str, Any]) -> Any:
    return query.trap_pack(GRAPH, _node(a["trap_id"], "trap")["id"])


def t_explain_link(a: dict[str, Any]) -> Any:
    return query.explain(GRAPH, a["from_id"], a["to_id"])


def t_list_corpus(a: dict[str, Any]) -> Any:
    rows = query.corpus(GRAPH)
    theme = (a.get("theme") or "").strip().lower()
    if theme:
        rows = [r for r in rows if any(theme in t.lower() for t in r.get("themes", []))]
    return _paginate(rows, int(a.get("limit", 25)), int(a.get("offset", 0)))


def t_prescreen(a: dict[str, Any]) -> Any:
    text = a.get("text") or ""
    if not text.strip():
        raise ValueError("`text` is required — pass the strategy document's text.")
    return {
        "hints": assess_mod.prescreen(text),
        "note": "Every hint is unverified. Read the passage before treating it as a finding.",
    }


def t_assess(a: dict[str, Any]) -> Any:
    return assess_mod.assess(GRAPH, _state(a))


def t_next_questions(a: dict[str, Any]) -> Any:
    return interview.next_questions(GRAPH, _state(a), limit=int(a.get("limit", 3)))


def t_coverage_report(a: dict[str, Any]) -> Any:
    return interview.coverage_report(GRAPH, _state(a))


def t_session_plan(a: dict[str, Any]) -> Any:
    return {"rounds": interview.session_plan(GRAPH, _state(a), rounds=int(a.get("rounds", 4)))}


READ_ONLY = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "strategy_load_context",
        "description": (
            "Load the assessment framework once per session: the pillars in assessment order, every "
            "principle, every failure pattern with its observable signals, every test with its pass/fail "
            "signals and weight, and every slot with what counts as sufficient. Call this first."
        ),
        "inputSchema": {"type": "object", "properties": {"response_format": FORMAT_SCHEMA}},
        "handler": t_load_context,
    },
    {
        "name": "strategy_search",
        "description": (
            "Search the graph by keyword across labels, aliases, summaries and question text. Use when "
            "the user names a concept and you need its node id."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "term": {"type": "string", "description": "e.g. 'promise to the customer'"},
                "types": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["pillar", "concept", "principle", "trap", "test", "slot", "question", "source"],
                    },
                    "description": "Restrict to these node types.",
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 12},
                "response_format": FORMAT_SCHEMA,
            },
            "required": ["term"],
        },
        "handler": t_search,
    },
    {
        "name": "strategy_get_pillar",
        "description": (
            "The full assessment kit for one area of strategy: its concepts, principles, failure patterns, "
            "tests ordered by severity, slots in order, and questions by depth."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "pillar_id": {"type": "string", "description": "e.g. pillar:how_to_win"},
                "response_format": FORMAT_SCHEMA,
            },
            "required": ["pillar_id"],
        },
        "handler": t_get_pillar,
    },
    {
        "name": "strategy_get_concept",
        "description": (
            "One concept with its practitioner note, what it is part of, what relates to it, the tests that "
            "evaluate it, the patterns confused with it, and its citations. Use when explaining a term."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "concept_id": {"type": "string", "description": "e.g. concept:wwhtbt"},
                "response_format": FORMAT_SCHEMA,
            },
            "required": ["concept_id"],
        },
        "handler": t_get_concept,
    },
    {
        "name": "strategy_get_test",
        "description": (
            "One test with its pass and fail signals, weight, severity, the questions that probe it, the "
            "failure patterns it catches, and which pillars it gates."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "test_id": {"type": "string", "description": "e.g. test:htw_single_logic"},
                "response_format": FORMAT_SCHEMA,
            },
            "required": ["test_id"],
        },
        "handler": t_get_test,
    },
    {
        "name": "strategy_get_trap",
        "description": (
            "One failure pattern with its observable signals, why it is costly, the coaching move for "
            "surfacing it without accusing anyone, and the tests that catch it."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "trap_id": {"type": "string", "description": "e.g. trap:initiative_list"},
                "response_format": FORMAT_SCHEMA,
            },
            "required": ["trap_id"],
        },
        "handler": t_get_trap,
    },
    {
        "name": "strategy_explain_link",
        "description": (
            "The shortest path between two nodes. Use to justify a question — why asking about channel "
            "bears on this user's way of winning."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "from_id": {"type": "string"},
                "to_id": {"type": "string"},
                "response_format": FORMAT_SCHEMA,
            },
            "required": ["from_id", "to_id"],
        },
        "handler": t_explain_link,
    },
    {
        "name": "strategy_list_corpus",
        "description": (
            "The indexed source material - title, URL, date and citation count - newest first, paginated. "
            "Metadata only; article text is not stored. Use for provenance and further reading."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "theme": {"type": "string", "description": "Filter to sources tagged with this theme."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 25},
                "offset": {"type": "integer", "minimum": 0, "default": 0},
                "response_format": FORMAT_SCHEMA,
            },
        },
        "handler": t_list_corpus,
    },
    {
        "name": "strategy_prescreen",
        "description": (
            "Cheap regex hints over a pasted strategy document, flagging passages worth reading closely. "
            "EVERY hint is unverified and must not be reported as a finding until you have read the "
            "passage and confirmed it. Not a substitute for assessment."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The strategy document's text."},
                "response_format": FORMAT_SCHEMA,
            },
            "required": ["text"],
        },
        "handler": t_prescreen,
    },
    {
        "name": "strategy_assess",
        "description": (
            "Turn a strategy state into per-pillar readiness and a priority-ranked gap list, plus blocking "
            "failures and any pillars gated by them. You supply the verdicts - the server never guesses "
            "them, because judging a way of winning is a reading task. 'unknown' scores zero but is "
            "reported separately as coverage, so 'not looked at yet' stays distinct from 'failing'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"state": STATE_SCHEMA, "response_format": FORMAT_SCHEMA},
            "required": ["state"],
        },
        "handler": t_assess,
    },
    {
        "name": "strategy_next_questions",
        "description": (
            "The ranked question queue for a state, each entry carrying why it was chosen. Priority: failed "
            "blocking test, then missing required slot in cascade order, then weak test by severity x "
            "weight, then suspected pattern, then depth, then unexamined pillar. ASK ONE OR TWO - the limit "
            "is how many to choose from, not how many to fire at the user."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "state": STATE_SCHEMA,
                "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 3},
                "response_format": FORMAT_SCHEMA,
            },
            "required": ["state"],
        },
        "handler": t_next_questions,
    },
    {
        "name": "strategy_coverage_report",
        "description": "Questions asked versus available, by pillar. Use to notice a session stuck in one area.",
        "inputSchema": {
            "type": "object",
            "properties": {"state": STATE_SCHEMA, "response_format": FORMAT_SCHEMA},
            "required": ["state"],
        },
        "handler": t_coverage_report,
    },
    {
        "name": "strategy_session_plan",
        "description": (
            "Preview several rounds of questioning, assuming answers land. For inspecting the policy - not "
            "a script to read aloud. Does not change state."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "state": STATE_SCHEMA,
                "rounds": {"type": "integer", "minimum": 1, "maximum": 10, "default": 4},
                "response_format": FORMAT_SCHEMA,
            },
            "required": ["state"],
        },
        "handler": t_session_plan,
    },
]

HANDLERS: dict[str, Callable[[dict[str, Any]], Any]] = {t["name"]: t["handler"] for t in TOOLS}
TOOL_SPECS = [
    {k: v for k, v in tool.items() if k != "handler"} | {"annotations": READ_ONLY} for tool in TOOLS
]


# --------------------------------------------------------------- protocol

def handle(request: dict[str, Any]) -> dict[str, Any] | None:
    method = request.get("method")
    request_id = request.get("id")
    params = request.get("params") or {}

    if method == "initialize":
        version = params.get("protocolVersion") or FALLBACK_PROTOCOL_VERSION
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": version,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "instructions": (
                    "A knowledge graph for coaching strategy. Assess the user's strategy and ask questions "
                    "so they can improve it. Never write, draft or complete the strategy for them - a "
                    "strategy the user did not choose is one they cannot defend or resource. Call "
                    "strategy_load_context first."
                ),
            },
        }

    if method in ("notifications/initialized", "notifications/cancelled"):
        return None

    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOL_SPECS}}

    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        handler = HANDLERS.get(name)
        if handler is None:
            known = ", ".join(sorted(HANDLERS))
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": tool_error(f"No tool named {name!r}. Available: {known}"),
            }
        try:
            payload = handler(arguments)
        except (ValueError, KeyError) as exc:
            # Tool-level failure: report inside the result so the agent can correct itself.
            return {"jsonrpc": "2.0", "id": request_id, "result": tool_error(str(exc))}
        except Exception:  # pragma: no cover - unexpected, keep the server alive
            log("unhandled error:\n" + traceback.format_exc())
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": tool_error("Internal error in the strategy graph server; see its stderr log."),
            }
        fmt = arguments.get("response_format", "markdown")
        return {"jsonrpc": "2.0", "id": request_id, "result": result(name, payload, fmt)}

    if request_id is None:
        return None  # unknown notification
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main() -> int:
    log(f"ready · {stats(GRAPH)['node_total']} nodes · {len(TOOLS)} tools · data {DATA_DIR}")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            sys.stdout.write(
                json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"Parse error: {exc}"}}) + "\n"
            )
            sys.stdout.flush()
            continue

        for req in request if isinstance(request, list) else [request]:
            response = handle(req)
            if response is not None:
                sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
