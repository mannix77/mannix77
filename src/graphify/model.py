"""Graph model: load the JSON node files, derive edges, validate integrity.

The data files are the source of truth. Most edges are *derived* from reference
fields on the nodes themselves (a question's ``probes``, a test's ``detects``,
and so on) so that the hand-maintained data stays readable and cannot drift out
of sync with the edge list. ``data/edges.json`` carries only the relationships
that no node field implies.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator

DATA_DIR = Path(__file__).resolve().parents[2] / "data"

# filename -> node type it contains
NODE_FILES: dict[str, str] = {
    "pillars.json": "pillar",
    "concepts.json": "concept",
    "principles.json": "principle",
    "traps.json": "trap",
    "tests.json": "test",
    "slots.json": "slot",
    "questions.json": "question",
    "sources.json": "source",
}

# reference field -> (edge type, permitted target types)
REF_FIELDS: dict[str, tuple[str, tuple[str, ...]]] = {
    "pillar": ("IN_PILLAR", ("pillar",)),
    "part_of": ("PART_OF", ("concept", "pillar")),
    "related": ("RELATED_TO", ("concept", "principle", "trap")),
    "contrasts_with": ("CONTRASTS_WITH", ("concept",)),
    "confused_with": ("CONFUSED_WITH", ("concept",)),
    "depends_on": ("DEPENDS_ON", ("slot",)),
    "evaluates": ("EVALUATES", ("concept",)),
    "detects": ("DETECTS", ("trap",)),
    "mitigated_by": ("MITIGATED_BY", ("test",)),
    "probes": ("PROBES", ("test",)),
    "covers": ("COVERS", ("slot",)),
    "slots": ("APPLIES_TO", ("slot",)),
    "follow_ups": ("FOLLOW_UP", ("question",)),
    "sources": ("CITES", ("source",)),
}

# every explicit edge type allowed in data/edges.json
EXPLICIT_EDGE_TYPES = {
    "PRECEDES",
    "GATES",
    "PAIRED_WITH",
    "PRODUCES",
    "FEEDS",
    "ENABLES",
    "TREATED_BY",
    "VIOLATES",
}

# node type -> required id prefix
ID_PREFIX = {
    "pillar": "pillar",
    "concept": "concept",
    "principle": "principle",
    "trap": "trap",
    "test": "test",
    "slot": "slot",
    "question": "q",
    "source": "src",
}

SEVERITIES = {"blocking": 3, "major": 2, "minor": 1}
ASK_WHEN = {"opening", "always", "slot_empty", "test_fail", "test_partial", "trap_hint", "deep", "closing"}
QUESTION_KINDS = {"opening", "clarifying", "probing", "challenge", "evidence", "reframe", "closing"}


@dataclass(frozen=True)
class Edge:
    src: str
    dst: str
    type: str
    derived: bool = False
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"from": self.src, "to": self.dst, "type": self.type, "derived": self.derived, "note": self.note}


@dataclass
class Graph:
    nodes: dict[str, dict[str, Any]] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    _out: dict[str, list[Edge]] = field(default_factory=dict, repr=False)
    _in: dict[str, list[Edge]] = field(default_factory=dict, repr=False)

    # -- construction ----------------------------------------------------
    def index(self) -> None:
        self._out, self._in = {}, {}
        for e in self.edges:
            self._out.setdefault(e.src, []).append(e)
            self._in.setdefault(e.dst, []).append(e)

    # -- access ----------------------------------------------------------
    def node(self, node_id: str) -> dict[str, Any]:
        try:
            return self.nodes[node_id]
        except KeyError:
            raise KeyError(f"unknown node id: {node_id!r}") from None

    def get(self, node_id: str) -> dict[str, Any] | None:
        return self.nodes.get(node_id)

    def by_type(self, node_type: str) -> list[dict[str, Any]]:
        return [n for n in self.nodes.values() if n["type"] == node_type]

    def out_edges(self, node_id: str, type: str | None = None) -> list[Edge]:
        es = self._out.get(node_id, [])
        return [e for e in es if type is None or e.type == type]

    def in_edges(self, node_id: str, type: str | None = None) -> list[Edge]:
        es = self._in.get(node_id, [])
        return [e for e in es if type is None or e.type == type]

    def targets(self, node_id: str, type: str) -> list[dict[str, Any]]:
        return [self.nodes[e.dst] for e in self.out_edges(node_id, type)]

    def sources_of(self, node_id: str, type: str) -> list[dict[str, Any]]:
        return [self.nodes[e.src] for e in self.in_edges(node_id, type)]

    def path(self, start: str, goal: str, max_depth: int = 6) -> list[str]:
        """Shortest undirected path between two nodes, for explainability."""
        if start not in self.nodes or goal not in self.nodes:
            return []
        seen, queue = {start}, [[start]]
        while queue:
            trail = queue.pop(0)
            if len(trail) > max_depth:
                return []
            cur = trail[-1]
            if cur == goal:
                return trail
            nbrs = [e.dst for e in self.out_edges(cur)] + [e.src for e in self.in_edges(cur)]
            for nxt in nbrs:
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(trail + [nxt])
        return []

    def pillars_in_order(self) -> list[dict[str, Any]]:
        return sorted(self.by_type("pillar"), key=lambda p: p.get("order", 0))

    def __iter__(self) -> Iterator[dict[str, Any]]:
        return iter(self.nodes.values())

    def __len__(self) -> int:
        return len(self.nodes)


def _iter_ref(value: Any) -> Iterable[str]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list):
        return tuple(v for v in value if isinstance(v, str))
    return ()


def load_graph(data_dir: Path | str = DATA_DIR) -> Graph:
    data_dir = Path(data_dir)
    graph = Graph()

    for filename, node_type in NODE_FILES.items():
        path = data_dir / filename
        records = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(records, list):
            raise ValueError(f"{filename}: expected a JSON array")
        for record in records:
            record.setdefault("type", node_type)
            node_id = record.get("id")
            if not node_id:
                raise ValueError(f"{filename}: record without an id: {record!r}")
            if node_id in graph.nodes:
                raise ValueError(f"duplicate node id {node_id!r} in {filename}")
            record["_file"] = filename
            graph.nodes[node_id] = record

    # derived edges from reference fields
    for node in graph.nodes.values():
        for field_name, (edge_type, _allowed) in REF_FIELDS.items():
            for target in _iter_ref(node.get(field_name)):
                graph.edges.append(Edge(node["id"], target, edge_type, derived=True))

    # explicit edges
    explicit_path = data_dir / "edges.json"
    if explicit_path.exists():
        for row in json.loads(explicit_path.read_text(encoding="utf-8")):
            graph.edges.append(
                Edge(row["from"], row["to"], row["type"], derived=False, note=row.get("note", ""))
            )

    graph.index()
    return graph


def validate(graph: Graph) -> list[str]:
    """Return a list of integrity problems. Empty list means the graph is sound."""
    errors: list[str] = []
    ids = set(graph.nodes)

    for node in graph.nodes.values():
        nid, ntype, where = node["id"], node["type"], node.get("_file", "?")
        prefix = ID_PREFIX[ntype]
        if not nid.startswith(f"{prefix}:"):
            errors.append(f"{where}: id {nid!r} should start with {prefix!r}:")

        for field_name, (_edge_type, allowed) in REF_FIELDS.items():
            for target in _iter_ref(node.get(field_name)):
                if target not in ids:
                    errors.append(f"{nid}.{field_name} -> unknown node {target!r}")
                elif graph.nodes[target]["type"] not in allowed:
                    got = graph.nodes[target]["type"]
                    errors.append(f"{nid}.{field_name} -> {target!r} is a {got}, expected one of {allowed}")

        if ntype in {"concept", "principle", "trap", "test", "slot", "question"} and not node.get("pillar"):
            errors.append(f"{nid}: missing pillar")

        if ntype == "test":
            if node.get("severity") not in SEVERITIES:
                errors.append(f"{nid}: severity must be one of {sorted(SEVERITIES)}")
            if not isinstance(node.get("weight"), int) or not 1 <= node["weight"] <= 5:
                errors.append(f"{nid}: weight must be an int 1-5")
            for key in ("statement", "why_it_matters"):
                if not node.get(key):
                    errors.append(f"{nid}: missing {key}")
            if not node.get("pass_signals") or not node.get("fail_signals"):
                errors.append(f"{nid}: needs both pass_signals and fail_signals")

        if ntype == "question":
            if node.get("kind") not in QUESTION_KINDS:
                errors.append(f"{nid}: kind must be one of {sorted(QUESTION_KINDS)}")
            if node.get("depth") not in (1, 2, 3):
                errors.append(f"{nid}: depth must be 1, 2 or 3")
            if not node.get("text", "").strip():
                errors.append(f"{nid}: missing text")
            if not node.get("intent"):
                errors.append(f"{nid}: missing intent")
            unknown = set(node.get("ask_when", [])) - ASK_WHEN
            if unknown:
                errors.append(f"{nid}: unknown ask_when values {sorted(unknown)}")
            if not node.get("ask_when"):
                errors.append(f"{nid}: needs at least one ask_when value")
            if not node.get("probes"):
                errors.append(f"{nid}: asks nothing testable (no probes)")

        if ntype == "trap":
            if not node.get("signals"):
                errors.append(f"{nid}: needs observable signals")
            if not node.get("mitigated_by"):
                errors.append(f"{nid}: no test would catch this trap")

        if ntype == "slot":
            if not isinstance(node.get("order"), int):
                errors.append(f"{nid}: order must be an int")

        if ntype == "source":
            if not node.get("url"):
                errors.append(f"{nid}: missing url")

    for edge in graph.edges:
        if edge.src not in ids:
            errors.append(f"edge {edge.type} from unknown node {edge.src!r}")
        if edge.dst not in ids:
            errors.append(f"edge {edge.type} to unknown node {edge.dst!r}")
        if not edge.derived and edge.type not in EXPLICIT_EDGE_TYPES:
            errors.append(f"edges.json: unknown edge type {edge.type!r}")

    # the PRECEDES chain and the pillars' order fields must tell the same story
    for edge in graph.edges:
        if edge.type != "PRECEDES":
            continue
        src, dst = graph.nodes.get(edge.src), graph.nodes.get(edge.dst)
        if not src or not dst:
            continue
        if src.get("order", 0) >= dst.get("order", 0):
            errors.append(
                f"PRECEDES {edge.src} -> {edge.dst} contradicts the order fields "
                f"({src.get('order')} >= {dst.get('order')})"
            )

    # coverage: every test should be reachable from at least one question
    probed = {e.dst for e in graph.edges if e.type == "PROBES"}
    for test in graph.by_type("test"):
        if test["id"] not in probed:
            errors.append(f"{test['id']}: no question probes this test")

    # coverage: every required slot should have at least one question covering it
    covered = {e.dst for e in graph.edges if e.type == "COVERS"}
    for slot in graph.by_type("slot"):
        if slot.get("required") and slot["id"] not in covered:
            errors.append(f"{slot['id']}: required slot has no question covering it")

    # every trap should be detectable by a question
    detected = {e.dst for e in graph.edges if e.type == "DETECTS" and graph.nodes[e.src]["type"] == "question"}
    for trap in graph.by_type("trap"):
        if trap["id"] not in detected:
            errors.append(f"{trap['id']}: no question detects this trap")

    return errors


def stats(graph: Graph) -> dict[str, Any]:
    counts = {t: len(graph.by_type(t)) for t in sorted(set(NODE_FILES.values()))}
    edge_counts: dict[str, int] = {}
    for e in graph.edges:
        edge_counts[e.type] = edge_counts.get(e.type, 0) + 1
    return {
        "nodes": counts,
        "node_total": len(graph),
        "edges": dict(sorted(edge_counts.items())),
        "edge_total": len(graph.edges),
        "pillars": [p["id"] for p in graph.pillars_in_order()],
    }
