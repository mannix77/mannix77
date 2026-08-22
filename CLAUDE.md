# mannix77 — strategy practitioner graph

## AI attribution policy (required)

Commit trailers are appended automatically by `.githooks/prepare-commit-msg`.
Run this once per clone:

```bash
bash scripts/ai-attribution/setup.sh
```

If commits are being refused with "the model id for this session is unknown",
either install the global recorder (`setup.sh --global-hooks`) or declare the
model for this clone with `git config ai.model <model-id>`. The hook refuses
rather than stamping a placeholder, because a non-blank filler value passes a
presence check and lets a commit merge green while declaring nothing.

When opening a PR, fill the **AI Attribution** block at the end of the body with
real values — the `AI attribution check` status rejects blanks and placeholders:

- `AI-Model:` — the model id for this session
- `AI-Session:` — the value of `$CLAUDE_CODE_SESSION_ID`
- `AI-Transcript:` — same reference as the commit trailers (`git log -1 --format=%B`)

A change made without AI assistance declares `AI-Assisted: none` instead.

Full policy: [`docs/AI_ATTRIBUTION.md`](docs/AI_ATTRIBUTION.md).

## Before you push

This project is **standard-library only** and has no build step. All four checks
run in CI; run them locally first:

```bash
PYTHONPATH=src python3 -m graphify validate      # must be clean
python3 -m unittest discover -s tests -t .
python3 tools/coverage_audit.py --strict
PYTHONPATH=src python3 -m graphify build
```

`validate` is the load-bearing one. It enforces referential integrity across the
data files, id conventions, that every test is probed by some question, that
every required slot is covered, that every trap is detectable, and that the
pillar `PRECEDES` chain agrees with the `order` fields.

## Repo-specific rules worth knowing

- **Do not add dependencies.** Stdlib-only is a deliberate design choice, not an
  oversight — it is what makes the graph portable to an MCP server, a Cloud Run
  container or a local bundle with no install step. Adding `pytest` would be a
  regression, not a convenience.
- **The agent never writes the user's strategy.** A test enforces that every
  question ends in a question mark and contains no authoring language. If a
  change makes that test fail, the change is wrong, not the test.
- **`data/*.json` is the source of truth.** `build/` is generated and gitignored.
- **Most edges are derived** from reference fields on the nodes rather than
  hand-listed in `edges.json`, so declare a relationship once, next to the thing
  it belongs to.
- **Don't delete a refuted gap register entry.** `data/coverage_gaps.json` keeps
  entries the corpus disproved, with a note recording what was assumed. A test
  enforces that they keep their explanation.
- **The corpus index is metadata only** — title, URL, date. No code path in
  `tools/refresh_corpus.py` retrieves article bodies, and a test rejects any body
  field that appears in an API response. Keep it that way.

## Layout

See [`README.md`](README.md) for the full map and
[`docs/data_model.md`](docs/data_model.md) for the schema.
