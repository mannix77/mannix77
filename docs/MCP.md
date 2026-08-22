# The MCP server

`strategy-graph` exposes the graph to any MCP client over stdio: 13 read-only
tools covering the surface described in
[`agent/tool_contract.md`](../agent/tool_contract.md).

## Build it

```bash
python3 tools/build_mcpb.py --verify
# -> dist/strategy-graph-0.1.0.mcpb   (~149 KB)
```

`--verify` speaks the protocol to the staged server before packaging — it runs
`initialize`, `tools/list` and a real `tools/call`, so a broken bundle fails the
build rather than the install. CI runs it on every push and uploads the bundle as
an artifact.

## Install it

**Desktop app:** open the `.mcpb` file. One file, nothing to resolve — the bundle
carries the graph and the code, and the project has no third-party dependencies.

**Any other client**, by config — this also runs straight from a checkout with no
build step:

```json
{
  "mcpServers": {
    "strategy-graph": {
      "command": "python3",
      "args": ["/path/to/mannix77/mcpb/server/main.py"]
    }
  }
}
```

The server locates its data by trying, in order: `server/lib/` (the installed
bundle), then `src/` and `data/` relative to the repo root (a checkout), then
`GRAPHIFY_DATA_DIR`. So the same entry point works in both layouts.

## The tools

| Tool | Use |
|---|---|
| `strategy_load_context` | Load the framework once per session. Call this first |
| `strategy_search` | Find a node id by keyword |
| `strategy_get_pillar` | The full assessment kit for one area |
| `strategy_get_concept` | A concept, its relations and citations |
| `strategy_get_test` | A test, its signals and probing questions |
| `strategy_get_trap` | A failure pattern, its signals and coaching move |
| `strategy_explain_link` | Shortest path between two nodes, to justify a question |
| `strategy_list_corpus` | The indexed sources, paginated. Metadata only |
| `strategy_prescreen` | Unverified regex hints over a pasted document |
| `strategy_assess` | Readiness, blocking failures, ranked gaps |
| `strategy_next_questions` | The ranked question queue, with reasons |
| `strategy_coverage_report` | Asked versus available, by pillar |
| `strategy_session_plan` | Preview the line of questioning |

Every tool is annotated `readOnlyHint: true`, `destructiveHint: false`,
`openWorldHint: false`. That is accurate rather than decorative: the graph is
immutable data, there are no outbound calls, and the caller owns the session
state and passes it in each time. Two identical calls always agree — there is a
test for it.

All tools take `response_format: markdown | json`. Structured data comes back in
`structuredContent` either way.

## Design decisions worth knowing

**No SDK.** Written against the standard library. The skill guidance recommends
the TypeScript SDK, and for most servers that is right — but this project's
portability argument rests on having no dependencies, and a stdio MCP server is a
JSON-RPC read/dispatch/write loop. The payoff is a bundle that installs with
nothing to resolve, and the same code running under Cloud Run later without a
rewrite.

**The protocol version is echoed, not hardcoded.** `initialize` returns whatever
version the client proposed, falling back to a constant only when the client
sends none. A hardcoded date-stamped version goes stale; echoing does not.

**Tool errors stay inside the result.** A bad node id or a malformed state comes
back as `isError: true` with a message naming the fix — often the closest
matching ids, found with `difflib` so a typo actually gets a suggestion. Only
genuine protocol faults (unknown method, unparseable frame) return a JSON-RPC
error. An agent can correct itself from the first kind; the second kind usually
kills the session.

**stdout carries protocol frames only.** All logging goes to stderr. A single
stray `print` corrupts the stream and the client drops the server, so there is a
test asserting stdout stays clean.

**The server never invents a verdict.** `strategy_assess` consumes
`pass`/`partial`/`fail`/`unknown` from the caller. Judging whether a stated way of
winning really resolves to a cost advantage is a reading task, and a regex that
guessed at it would be worse than useless — it would be confidently wrong. The
`instructions` field returned by `initialize` also carries the non-authoring rule,
so a client that reads it gets the constraint without the system prompt.

## What this does not do

It does not archive transcripts, hold state, or reach the network. If you want the
coaching discipline enforced as well as offered, the system prompt in
[`agent/system_prompt.md`](../agent/system_prompt.md) is what does that — on a
platform where you do not control the prompt, a generic assistant with these
tools will cheerfully draft the user's strategy, which defeats the point.

## Not yet verified

The bundle builds and round-trips the protocol in CI, and the staged tree runs
standalone outside the repo. Installing the `.mcpb` through the desktop app has
not been exercised from this environment. If the host cannot resolve `python` on
your machine, change `server.mcp_config.command` in `mcpb/manifest.json` to
`python3` and rebuild.
