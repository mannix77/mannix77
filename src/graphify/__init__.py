"""graphify - a queryable knowledge graph for strategy coaching.

The graph encodes the *practitioner method* drawn from Roger L. Martin's
Strategy Practitioner Insights series: the areas a strategy has to answer for,
the tests a strategy has to survive, the failure patterns to watch for, and the
questions that surface each of them.

It exists to drive an agent that interrogates a user's strategy. The agent
assesses and asks; it does not author strategy on the user's behalf.

Public surface:

    from graphify import load_graph, query, assess, interview

    graph = load_graph()
    report = assess.assess(graph, assess.StrategyState.from_dict(state))
    asks = interview.next_questions(graph, state_obj, report=report)
"""

from .model import Graph, load_graph, stats, validate  # noqa: F401

__all__ = ["Graph", "load_graph", "stats", "validate", "query", "assess", "interview", "build"]
__version__ = "0.1.0"
