## What this changes

<!-- What moved, and why. If it touches data/, say which node types and how many. -->

## Checks

<!-- Tick what you ran locally. CI runs all of them. -->

- [ ] `PYTHONPATH=src python3 -m graphify validate` is clean
- [ ] `python3 -m unittest discover -s tests -t .` passes
- [ ] `python3 tools/coverage_audit.py --strict` passes
- [ ] If a test, trap or required slot was added, it is reachable from a question

## Notes for review

<!-- Anything a reviewer would otherwise have to reconstruct: a judgement call, a
     trade-off, something deliberately left out, a gap register entry you changed. -->

<!--
Keep the AI Attribution block LAST. The checker selects the final
blank-line-delimited paragraph containing an AI- line, so anything appended
after it — release notes, review-bot summaries — is fine, but a second trailer
block is not.

`git log -1 --format=%B` on the head commit shows the values to copy.
For a change made without AI assistance, replace the whole block with:
AI-Assisted: none
-->

AI-Model:
AI-Session:
AI-Transcript:
