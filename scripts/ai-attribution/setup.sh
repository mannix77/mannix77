#!/usr/bin/env bash
# One-time developer setup for AI attribution.
#
#   bash scripts/ai-attribution/setup.sh                  # point git at .githooks
#   bash scripts/ai-attribution/setup.sh --global-hooks   # also record the model in every session
#
# Why --global-hooks matters more than it looks: the SessionStart recorder is
# registered in this repo's .claude/settings.json, so it only fires for sessions
# started inside a project that registers it. Start a session elsewhere, commit
# to this repo from there, and no model id is ever recorded — at which point the
# commit hook refuses the commit.
#
# The global install copies ONLY the recorder. It writes to
# ~/.claude/ai-attribution/ and makes no network calls.
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

git config core.hooksPath .githooks
chmod +x .githooks/* scripts/ai-attribution/*.sh 2>/dev/null || true
echo "core.hooksPath -> .githooks"

if [ "${1:-}" = "--global-hooks" ]; then
  GLOBAL_HOOKS="$HOME/.claude/hooks"
  GLOBAL_SETTINGS="$HOME/.claude/settings.json"
  mkdir -p "$GLOBAL_HOOKS" "$HOME/.claude/ai-attribution"
  cp .claude/hooks/session_start.py "$GLOBAL_HOOKS/session_start.py"
  chmod +x "$GLOBAL_HOOKS/session_start.py"
  echo "recorder -> $GLOBAL_HOOKS/session_start.py"

  python3 - "$GLOBAL_SETTINGS" "$GLOBAL_HOOKS/session_start.py" <<'PY'
import json, sys, pathlib
settings_path, hook_path = pathlib.Path(sys.argv[1]), sys.argv[2]
settings = {}
if settings_path.exists():
    try:
        settings = json.loads(settings_path.read_text() or "{}")
    except json.JSONDecodeError:
        print(f"! {settings_path} is not valid JSON — leaving it alone", file=sys.stderr)
        raise SystemExit(1)

hooks = settings.setdefault("hooks", {}).setdefault("SessionStart", [])
command = f"python3 {hook_path}"
already = any(
    command in json.dumps(entry) for entry in hooks
)
if already:
    print("SessionStart recorder already registered globally")
else:
    hooks.append({"hooks": [{"type": "command", "command": command}]})
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings, indent=2) + "\n")
    print(f"registered SessionStart recorder in {settings_path}")
PY
else
  cat <<'EOF'

Not installed globally. Sessions started outside this project will not record a
model id, and the commit hook will refuse those commits. Either re-run with
--global-hooks, or declare the model for this clone:

  git config ai.model <model-id>
EOF
fi
