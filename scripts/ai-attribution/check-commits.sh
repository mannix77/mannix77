#!/usr/bin/env bash
# Verify AI attribution trailers on a range of commits.
#
#   scripts/ai-attribution/check-commits.sh <range>
#   scripts/ai-attribution/check-commits.sh origin/master..HEAD
#
# Exit 0 when every non-exempt commit declares its provenance, 1 otherwise.
# CI can enforce that metadata is present and well-formed; it cannot enforce
# that it is true. The archived transcript is what makes a false claim
# detectable.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TRAILER_BLOCK="$HERE/trailer-block.sh"

# Commits at or before this point predate the policy and are grandfathered.
# They carry the older Co-Authored-By / Claude-Session convention. Without a
# boundary, adopting this check would flag the entire existing history on the
# first run.
: "${AI_ATTRIBUTION_SINCE:=5c262d61c8b05223b0ed681dd0651ee78a6c2370}"

RANGE="${1:-}"
if [ -z "$RANGE" ]; then
  echo "usage: $0 <git-range>" >&2
  exit 2
fi

PLACEHOLDERS='^(unknown|none|n/?a|tbd|todo|xxx+|\.\.\.|<.*>|\$\{?[A-Z_]+\}?)$'
fail=0
checked=0
skipped=0

while read -r sha; do
  [ -z "$sha" ] && continue

  # Grandfathered history.
  if [ -n "$AI_ATTRIBUTION_SINCE" ] && git merge-base --is-ancestor "$sha" "$AI_ATTRIBUTION_SINCE" 2>/dev/null; then
    skipped=$((skipped + 1))
    continue
  fi

  # Merge commits carry no authored change of their own.
  if [ "$(git rev-list --parents -n 1 "$sha" | wc -w)" -gt 2 ]; then
    skipped=$((skipped + 1))
    continue
  fi

  author="$(git log -1 --format='%an <%ae>' "$sha")"
  if printf '%s' "$author" | grep -qE '\[bot\]|users\.noreply\.github\.com$.*\[bot\]'; then
    skipped=$((skipped + 1))
    continue
  fi

  block="$(git log -1 --format='%B' "$sha" | bash "$TRAILER_BLOCK")"
  short="$(git log -1 --format='%h %s' "$sha")"
  checked=$((checked + 1))

  value() { printf '%s\n' "$block" | grep -m1 -E "^$1:" | sed -E "s/^$1:[[:space:]]*//"; }

  assisted="$(value 'AI-Assisted')"
  model="$(value 'AI-Model')"
  session="$(value 'AI-Session')"

  # An explicit "no AI involved" declaration is complete on its own.
  if [ "$(printf '%s' "$assisted" | tr '[:upper:]' '[:lower:]')" = "none" ]; then
    continue
  fi

  problems=()
  [ -z "$model" ] && problems+=("missing AI-Model")
  [ -z "$session" ] && problems+=("missing AI-Session")

  for pair in "AI-Model:$model" "AI-Session:$session"; do
    key="${pair%%:*}"; val="${pair#*:}"
    if [ -n "$val" ] && printf '%s' "$val" | tr '[:upper:]' '[:lower:]' | grep -qE "$PLACEHOLDERS"; then
      problems+=("$key is a placeholder: '$val'")
    fi
  done

  if [ "${#problems[@]}" -gt 0 ]; then
    echo "FAIL $short" >&2
    for p in "${problems[@]}"; do echo "       - $p" >&2; done
    fail=1
  fi
done < <(git rev-list "$RANGE" 2>/dev/null)

if [ "$fail" -ne 0 ]; then
  cat >&2 <<'EOF'

Every commit must declare its AI provenance. Either:

  AI-Model:      the model id for the session
  AI-Session:    the session id
  AI-Transcript: where the transcript is archived   (optional but expected)

or, for a change made without AI assistance:

  AI-Assisted: none

Run `bash scripts/ai-attribution/setup.sh` once so the trailers are appended
automatically, or add them by hand. See docs/AI_ATTRIBUTION.md.
EOF
  exit 1
fi

echo "ai-attribution: $checked commit(s) verified, $skipped exempt"
