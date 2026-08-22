#!/usr/bin/env python3
"""Assemble the .mcpb bundle - a single installable file, nothing to resolve.

    python3 tools/build_mcpb.py              # -> dist/strategy-graph-<version>.mcpb
    python3 tools/build_mcpb.py --verify     # build, then round-trip the protocol against it

Layout produced inside the archive, per the MCPB manifest spec:

    manifest.json
    server/main.py
    server/lib/graphify/...     the package
    server/lib/data/*.json      the graph

`server/lib` is what PYTHONPATH points at. Because this project has no third-party
dependencies, that directory holds only our own code - which is the whole reason
the bundle can be a plain copy with no install step.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MCPB = ROOT / "mcpb"
DIST = ROOT / "dist"

# Data files the server actually reads. coverage_gaps.json is read by the audit
# tool, not by the graph loader, so it is deliberately left out of the bundle.
DATA_FILES = [
    "pillars.json",
    "concepts.json",
    "principles.json",
    "traps.json",
    "tests.json",
    "slots.json",
    "questions.json",
    "sources.json",
    "edges.json",
]


def stage(target: Path) -> dict:
    manifest = json.loads((MCPB / "manifest.json").read_text(encoding="utf-8"))

    shutil.copy2(MCPB / "manifest.json", target / "manifest.json")

    server = target / "server"
    (server / "lib").mkdir(parents=True)
    shutil.copy2(MCPB / "server" / "main.py", server / "main.py")

    shutil.copytree(
        ROOT / "src" / "graphify",
        server / "lib" / "graphify",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )

    data = server / "lib" / "data"
    data.mkdir()
    for name in DATA_FILES:
        source = ROOT / "data" / name
        if not source.exists():
            raise SystemExit(f"missing data file: {source}")
        shutil.copy2(source, data / name)

    for extra in ("README.md",):
        if (ROOT / extra).exists():
            shutil.copy2(ROOT / extra, target / extra)

    return manifest


def archive(staged: Path, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(staged.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(staged).as_posix())
    return out


def verify(staged: Path) -> None:
    """Speak the protocol to the staged server: initialize, list, then call a tool."""
    frames = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "build-verify", "version": "0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "strategy_next_questions",
                    "arguments": {"state": {"asked": []}, "limit": 2, "response_format": "json"}}},
    ]
    proc = subprocess.run(
        [sys.executable, str(staged / "server" / "main.py")],
        input="\n".join(json.dumps(f) for f in frames) + "\n",
        capture_output=True,
        text=True,
        timeout=120,
    )
    responses = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    by_id = {r.get("id"): r for r in responses}

    init = by_id.get(1, {}).get("result", {})
    if init.get("serverInfo", {}).get("name") != "strategy-graph":
        raise SystemExit(f"initialize failed: {responses}\n{proc.stderr}")

    tools = by_id.get(2, {}).get("result", {}).get("tools", [])
    if not tools:
        raise SystemExit(f"tools/list returned nothing: {proc.stderr}")

    call = by_id.get(3, {}).get("result", {})
    if call.get("isError") or not call.get("content"):
        raise SystemExit(f"tools/call failed: {call}\n{proc.stderr}")

    print(f"verify: initialize ok, {len(tools)} tools, tools/call ok")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--verify", action="store_true", help="round-trip the protocol against the staged server")
    parser.add_argument("--out", help="output path for the .mcpb file")
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory() as tmp:
        staged = Path(tmp) / "bundle"
        staged.mkdir()
        manifest = stage(staged)

        if args.verify:
            verify(staged)

        out = Path(args.out) if args.out else DIST / f"{manifest['name']}-{manifest['version']}.mcpb"
        archive(staged, out)

    size_kb = out.stat().st_size / 1024
    print(f"built {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}  ({size_kb:.0f} KB)")
    print("install: open it with the desktop app, or add the manifest's mcp_config to your client")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
