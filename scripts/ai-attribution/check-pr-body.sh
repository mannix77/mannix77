#!/usr/bin/env bash
# Verify the AI attribution block in a pull request description.
#
#   scripts/ai-attribution/check-pr-body.sh <file-containing-pr-body>
#   ... | scripts/ai-attribution/check-pr-body.sh -
#
# The PR body matters because it is what survives a squash merge: GitHub builds
# the squash commit message from the PR title and body, so the fields validated
# here are the ones that land on the default branch.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE="${1:--}"

if [ "$SOURCE" = "-" ]; then
  body="$(cat)"
else
  body="$(cat "$SOURCE")"
fi

block="$(printf '%s\n' "$body" | bash "$HERE/trailer-block.sh")"
PLACEHOLDERS='^(unknown|none|n/?a|tbd|todo|xxx+|\.\.\.|<.*>|\$\{?[a-z_]+\}?|the model id.*|paste .*)$'

value() { printf '%s\n' "$block" | grep -m1 -E "^$1:" | sed -E "s/^$1:[[:space:]]*//"; }

assisted="$(value 'AI-Assisted')"
model="$(value 'AI-Model')"
session="$(value 'AI-Session')"

if [ "$(printf '%s' "$assisted" | tr '[:upper:]' '[:lower:]')" = "none" ]; then
  echo "ai-attribution: PR declares no AI assistance"
  exit 0
fi

problems=()
[ -z "$block" ] && problems+=("no AI-* trailer block found in the PR description")
[ -z "$model" ] && problems+=("missing AI-Model")
[ -z "$session" ] && problems+=("missing AI-Session")

for pair in "AI-Model:$model" "AI-Session:$session"; do
  key="${pair%%:*}"; val="${pair#*:}"
  if [ -n "$val" ] && printf '%s' "$val" | tr '[:upper:]' '[:lower:]' | grep -qE "$PLACEHOLDERS"; then
    problems+=("$key still holds the template placeholder: '$val'")
  fi
done

if [ "${#problems[@]}" -gt 0 ]; then
  echo "FAIL: pull request description" >&2
  for p in "${problems[@]}"; do echo "       - $p" >&2; done
  cat >&2 <<'EOF'

Fill the AI Attribution block at the end of the PR description with real values.
`git log -1 --format=%B` on the head commit shows the values to copy.
EOF
  exit 1
fi

echo "ai-attribution: PR description verified (model=$model)"
