#!/usr/bin/env python3
"""Record the session's model id and transcript path for the git commit hook.

SessionStart is the only Claude Code hook that receives the model id, so this is
the only place it can be captured. It writes a small shell-sourceable state file
that .githooks/prepare-commit-msg reads when building trailers.

Writes to ~/.claude/ai-attribution/<session>.env. No network calls, no writes
inside the repository.

Safe to install globally (see scripts/ai-attribution/setup.sh --global-hooks) —
the transcript-archiving side is deliberately NOT global, because registered
globally it would ship transcripts of unrelated work into this repo's archive.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys


def shell_quote(value: str) -> str:
    return "'" + str(value).replace("'", "'\"'\"'") + "'"


def main() -> int:
    try:
        payload = json.load(sys.stdin) if not sys.stdin.isatty() else {}
    except json.JSONDecodeError:
        payload = {}

    session = (
        payload.get("session_id")
        or os.environ.get("CLAUDE_CODE_SESSION_ID")
        or os.environ.get("CLAUDE_CODE_REMOTE_SESSION_ID")
        or ""
    )
    if not session:
        # Nothing to key the state file on; the commit hook will refuse rather
        # than stamp a placeholder, which is the intended failure.
        return 0

    model = payload.get("model") or ""
    if isinstance(model, dict):
        model = model.get("id") or model.get("display_name") or ""
    model = model or os.environ.get("ANTHROPIC_MODEL", "")

    transcript = payload.get("transcript_path") or ""

    state_dir = pathlib.Path(
        os.environ.get("AI_ATTRIBUTION_STATE_DIR")
        or (pathlib.Path.home() / ".claude" / "ai-attribution")
    )
    state_dir.mkdir(parents=True, exist_ok=True)

    lines = [f"AI_MODEL={shell_quote(model)}" if model else "AI_MODEL=''"]
    if transcript:
        lines.append(f"AI_TRANSCRIPT={shell_quote(transcript)}")
    (state_dir / f"{session}.env").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
