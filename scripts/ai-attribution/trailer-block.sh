#!/usr/bin/env bash
# Extract the AI attribution trailer block from a commit message or PR body.
#
# Selects the LAST blank-line-delimited paragraph that contains a line starting
# with "AI-", and rejoins values GitHub has line-wrapped.
#
# Two decisions here are load-bearing, both inherited from the policy:
#
#   * Not "scan the whole message". Any prose that quotes the trailer format
#     would then be indistinguishable from a real trailer, so a docs change
#     describing this policy fails its own check.
#   * Not "the last paragraph". GitHub builds a squash commit message from the
#     PR body, and review bots append release notes after the author's content,
#     so real trailers routinely sit above the end of the message.
#
# Reads the message on stdin, writes the normalised block on stdout.
set -euo pipefail

awk '
  # Accumulate paragraphs; remember the last one containing an AI- line.
  {
    if ($0 ~ /^[[:space:]]*$/) {
      if (has_ai) { block = para }
      para = ""; has_ai = 0; next
    }
    para = para $0 "\n"
    if ($0 ~ /^AI-[A-Za-z-]+:/) { has_ai = 1 }
  }
  END {
    if (has_ai) { block = para }
    printf "%s", block
  }
' | awk '
  # Rejoin folded continuation lines: a line that is not itself a trailer key
  # belongs to the previous trailer value.
  /^AI-[A-Za-z-]+:/ || /^[A-Za-z][A-Za-z-]*:/ {
    if (cur != "") { print cur }
    cur = $0; next
  }
  {
    sub(/^[[:space:]]+/, "", $0)
    cur = cur $0
  }
  END { if (cur != "") { print cur } }
'
