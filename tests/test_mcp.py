"""Protocol-level tests for the MCP server.

These drive the real server as a subprocess over stdio, the way a client does,
rather than importing its handlers. That is the only way to catch the failure
modes that actually break an MCP integration: a stray write to stdout, a
malformed frame, a tool error escaping as a protocol error.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "mcpb" / "server" / "main.py"

INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}


def roundtrip(*frames: dict) -> tuple[dict, str]:
    """Send frames, return ({id: response}, stderr)."""
    payload = "\n".join(json.dumps(f) for f in (INIT, *frames)) + "\n"
    proc = subprocess.run(
        [sys.executable, str(SERVER)], input=payload, capture_output=True, text=True, timeout=120
    )
    responses = {}
    for line in proc.stdout.splitlines():
        if line.strip():
            frame = json.loads(line)  # a non-JSON line here is itself the bug
            responses[frame.get("id")] = frame
    return responses, proc.stderr


def call(name: str, arguments: dict, request_id: int = 9) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }


class TestHandshake(unittest.TestCase):
    def test_initialize_identifies_the_server(self):
        responses, _ = roundtrip()
        result = responses[1]["result"]
        self.assertEqual(result["serverInfo"]["name"], "strategy-graph")
        self.assertIn("tools", result["capabilities"])

    def test_initialize_echoes_the_clients_protocol_version(self):
        """Echoing avoids the server going stale as the spec revs."""
        responses, _ = roundtrip()
        self.assertEqual(responses[1]["result"]["protocolVersion"], "2025-06-18")

    def test_instructions_state_the_non_authoring_rule(self):
        responses, _ = roundtrip()
        instructions = responses[1]["result"]["instructions"].lower()
        self.assertIn("never write", instructions)

    def test_notifications_get_no_response(self):
        responses, _ = roundtrip({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.assertEqual(set(responses), {1})

    def test_unknown_method_is_a_protocol_error(self):
        responses, _ = roundtrip({"jsonrpc": "2.0", "id": 5, "method": "does/not/exist"})
        self.assertEqual(responses[5]["error"]["code"], -32601)

    def test_malformed_line_does_not_kill_the_server(self):
        payload = json.dumps(INIT) + "\nnot json at all\n" + json.dumps(call("strategy_load_context", {}, 7)) + "\n"
        proc = subprocess.run(
            [sys.executable, str(SERVER)], input=payload, capture_output=True, text=True, timeout=120
        )
        frames = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
        codes = [f.get("error", {}).get("code") for f in frames]
        self.assertIn(-32700, codes, "expected a parse error frame")
        self.assertTrue(any(f.get("id") == 7 for f in frames), "server should keep serving after bad input")

    def test_stdout_carries_only_protocol_frames(self):
        """Any diagnostic on stdout corrupts the stream; logs must go to stderr."""
        responses, stderr = roundtrip(call("strategy_load_context", {}, 3))
        self.assertIn("ready", stderr, "startup log should go to stderr")
        self.assertEqual(set(responses), {1, 3})


class TestToolSurface(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        responses, _ = roundtrip({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        cls.tools = responses[2]["result"]["tools"]

    def test_every_tool_is_namespaced(self):
        self.assertGreaterEqual(len(self.tools), 13)
        for tool in self.tools:
            self.assertTrue(tool["name"].startswith("strategy_"), tool["name"])

    def test_every_tool_has_a_description_and_schema(self):
        for tool in self.tools:
            with self.subTest(tool=tool["name"]):
                self.assertGreater(len(tool["description"]), 40, "descriptions guide tool selection")
                self.assertEqual(tool["inputSchema"]["type"], "object")

    def test_every_tool_is_annotated_read_only(self):
        """The graph is immutable and the caller owns session state."""
        for tool in self.tools:
            with self.subTest(tool=tool["name"]):
                self.assertTrue(tool["annotations"]["readOnlyHint"])
                self.assertFalse(tool["annotations"]["destructiveHint"])
                self.assertFalse(tool["annotations"]["openWorldHint"])

    def test_required_fields_are_declared(self):
        by_name = {t["name"]: t for t in self.tools}
        self.assertIn("term", by_name["strategy_search"]["inputSchema"]["required"])
        self.assertIn("state", by_name["strategy_assess"]["inputSchema"]["required"])

    def test_prescreen_description_warns_the_hints_are_unverified(self):
        by_name = {t["name"]: t for t in self.tools}
        self.assertIn("unverified", by_name["strategy_prescreen"]["description"].lower())

    def test_manifest_tool_list_matches_the_server(self):
        manifest = json.loads((ROOT / "mcpb" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(
            sorted(t["name"] for t in manifest["tools"]),
            sorted(t["name"] for t in self.tools),
            "manifest and server disagree about the tool list",
        )


class TestToolBehaviour(unittest.TestCase):
    def test_load_context_returns_the_framework(self):
        responses, _ = roundtrip(call("strategy_load_context", {"response_format": "json"}, 3))
        payload = responses[3]["result"]["structuredContent"]
        self.assertEqual(len(payload["pillars"]), 12)
        self.assertTrue(payload["tests"])
        self.assertTrue(payload["slots"])

    def test_next_questions_explains_itself(self):
        responses, _ = roundtrip(
            call("strategy_next_questions", {"state": {"asked": []}, "limit": 2, "response_format": "json"}, 3)
        )
        text = responses[3]["result"]["content"][0]["text"]
        items = json.loads(text)
        self.assertTrue(items)
        for item in items:
            self.assertTrue(item["reason"])
            self.assertTrue(item["because"])

    def test_assess_separates_unknown_from_failing(self):
        responses, _ = roundtrip(
            call("strategy_assess", {"state": {"verdicts": {}}, "response_format": "json"}, 3)
        )
        payload = responses[3]["result"]["structuredContent"]
        self.assertEqual(payload["assessment_coverage"], 0.0)
        self.assertEqual(payload["gaps"], [], "unknown is not a gap")

    def test_bad_state_is_a_tool_error_with_guidance(self):
        """A tool failure must not surface as a protocol error."""
        responses, _ = roundtrip(
            call("strategy_assess", {"state": {"verdicts": {"test:nope": "pass"}}}, 3)
        )
        result = responses[3]["result"]
        self.assertTrue(result["isError"])
        self.assertNotIn("error", responses[3])
        self.assertIn("strategy_load_context", result["content"][0]["text"])

    def test_unknown_tool_lists_the_alternatives(self):
        responses, _ = roundtrip(call("strategy_nonexistent", {}, 3))
        text = responses[3]["result"]["content"][0]["text"]
        self.assertTrue(responses[3]["result"]["isError"])
        self.assertIn("strategy_assess", text)

    def test_unknown_node_suggests_close_matches(self):
        responses, _ = roundtrip(call("strategy_get_concept", {"concept_id": "concept:where_to_plai"}, 3))
        result = responses[3]["result"]
        self.assertTrue(result["isError"])
        self.assertIn("concept:where_to_play", result["content"][0]["text"])

    def test_corpus_paginates(self):
        responses, _ = roundtrip(
            call("strategy_list_corpus", {"limit": 5, "offset": 0, "response_format": "json"}, 3)
        )
        payload = responses[3]["result"]["structuredContent"]
        self.assertEqual(payload["count"], 5)
        self.assertTrue(payload["has_more"])
        self.assertEqual(payload["next_offset"], 5)
        self.assertGreater(payload["total"], 200)

    def test_prescreen_flags_and_labels_hints(self):
        responses, _ = roundtrip(
            call("strategy_prescreen", {"text": "Our moat is unassailable. Customers should recognise this."}, 3)
        )
        text = responses[3]["result"]["content"][0]["text"]
        self.assertIn("trap:moat_thinking", text)
        self.assertIn("nverified", text)

    def test_markdown_is_the_default_and_json_is_available(self):
        responses, _ = roundtrip(
            call("strategy_assess", {"state": {"verdicts": {"test:contains_a_bet": "fail"}}}, 3),
            call("strategy_assess", {"state": {"verdicts": {"test:contains_a_bet": "fail"}}, "response_format": "json"}, 4),
        )
        markdown = responses[3]["result"]["content"][0]["text"]
        as_json = responses[4]["result"]["content"][0]["text"]
        self.assertIn("**Blocking failures**", markdown)
        json.loads(as_json)

    def test_missing_required_argument_is_reported_clearly(self):
        responses, _ = roundtrip(call("strategy_search", {}, 3))
        self.assertTrue(responses[3]["result"]["isError"])
        self.assertIn("term", responses[3]["result"]["content"][0]["text"])

    def test_session_plan_does_not_leak_state_between_calls(self):
        """The server is stateless; identical calls must agree."""
        first, _ = roundtrip(call("strategy_next_questions", {"state": {"asked": []}, "response_format": "json"}, 3))
        second, _ = roundtrip(call("strategy_next_questions", {"state": {"asked": []}, "response_format": "json"}, 3))
        self.assertEqual(
            first[3]["result"]["content"][0]["text"], second[3]["result"]["content"][0]["text"]
        )


class TestBundle(unittest.TestCase):
    def test_manifest_declares_the_required_fields(self):
        manifest = json.loads((ROOT / "mcpb" / "manifest.json").read_text(encoding="utf-8"))
        for field in ("manifest_version", "name", "version", "description", "author", "server"):
            self.assertIn(field, manifest)
        self.assertIn("name", manifest["author"])
        server = manifest["server"]
        self.assertEqual(server["type"], "python")
        self.assertEqual(server["entry_point"], "server/main.py")
        self.assertIn("command", server["mcp_config"])

    def test_manifest_paths_use_the_dirname_variable(self):
        """Absolute paths baked into a manifest break on every other machine."""
        config = json.dumps(
            json.loads((ROOT / "mcpb" / "manifest.json").read_text(encoding="utf-8"))["server"]["mcp_config"]
        )
        self.assertIn("${__dirname}", config)
        self.assertNotIn("/home/", config)

    def test_builder_stages_code_and_data(self):
        import tempfile

        sys.path.insert(0, str(ROOT / "tools"))
        import build_mcpb

        with tempfile.TemporaryDirectory() as tmp:
            staged = Path(tmp) / "bundle"
            staged.mkdir()
            manifest = build_mcpb.stage(staged)
            self.assertEqual(manifest["name"], "strategy-graph")
            self.assertTrue((staged / "manifest.json").is_file())
            self.assertTrue((staged / "server" / "main.py").is_file())
            self.assertTrue((staged / "server" / "lib" / "graphify" / "model.py").is_file())
            for name in build_mcpb.DATA_FILES:
                self.assertTrue((staged / "server" / "lib" / "data" / name).is_file(), name)

    def test_bundled_layout_runs_without_the_repo(self):
        """The staged tree must be self-sufficient - that is the point of the bundle."""
        import tempfile

        sys.path.insert(0, str(ROOT / "tools"))
        import build_mcpb

        with tempfile.TemporaryDirectory() as tmp:
            staged = Path(tmp) / "bundle"
            staged.mkdir()
            build_mcpb.stage(staged)
            proc = subprocess.run(
                [sys.executable, str(staged / "server" / "main.py")],
                input=json.dumps(INIT) + "\n" + json.dumps(call("strategy_load_context", {}, 3)) + "\n",
                capture_output=True,
                text=True,
                timeout=120,
                cwd=tmp,
            )
            ids = [json.loads(l)["id"] for l in proc.stdout.splitlines() if l.strip()]
            self.assertIn(3, ids, proc.stderr)


if __name__ == "__main__":
    unittest.main()
