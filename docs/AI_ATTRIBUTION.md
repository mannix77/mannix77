# AI Attribution Policy

Every commit and pull request in this repository declares its AI provenance:
which model produced the change and where the session can be traced. Presence
and format are machine-enforced. The trust model is "declared metadata, verified
by CI, auditable via the session record" — the same shape as a DCO sign-off.

Ported from the `stock-analyzer` policy. What differs here is recorded under
[Differences from stock-analyzer](#differences-from-stock-analyzer).

## The metadata

Commits made during a Claude Code session get these trailers appended
automatically:

```
AI-Model: claude-opus-5
AI-Session: b22aa90d-a631-58f7-8b23-ae20e0a392a0
AI-Transcript: /root/.claude/projects/-home-user-mannix77/<session>.jsonl
```

Commits made without AI assistance get `AI-Assisted: none`. The git author stays
the accountable human; the model is metadata, not the author.

`AI-Model` and `AI-Session` are required. `AI-Transcript` is expected but not
enforced — see [Transcript archiving](#transcript-archiving-not-yet-ported).

PR descriptions carry the same fields. That matters because the PR body is what
survives a squash merge: GitHub builds the squash commit message from the title
and body, so those are the fields that land on `master`.

## How it's produced

| Piece | Role |
|---|---|
| `.githooks/prepare-commit-msg` | Appends the trailers on every commit. Detects a session via the `CLAUDECODE` / `CLAUDE_CODE_SESSION_ID` variables Claude Code exports to Bash. |
| `.claude/hooks/session_start.py` | SessionStart is the only hook that receives the model id, so it is the only place it can be captured. Writes model and transcript path to `~/.claude/ai-attribution/<session>.env`. |
| `scripts/ai-attribution/setup.sh` | Points `core.hooksPath` at `.githooks`; `--global-hooks` also installs the recorder. |

One-time setup:

```bash
bash scripts/ai-attribution/setup.sh                  # hooks for this clone
bash scripts/ai-attribution/setup.sh --global-hooks   # also record the model in every session
```

`--global-hooks` matters more than it looks. The recorder is registered in this
repo's `.claude/settings.json`, so it only fires for sessions started inside a
project that registers it. Start a session in `~`, commit to this repo from
there, and no model id is ever recorded.

The obvious handling of that case — stamp `AI-Model: unknown` — is wrong, and
this is the single most valuable detail in the original policy: `unknown` is
non-blank, so it passes a presence check. A commit merges green while declaring
nothing. So the commit hook **refuses the commit**, and `check-commits.sh`
rejects `unknown` and other placeholders on the CI side too.

If you would rather not install a global hook, declare the model per clone:

```bash
git config ai.model claude-opus-5
```

The global install copies **only** the recorder, writes to
`~/.claude/ai-attribution/`, and makes no network calls.

## How it's enforced

- **`AI attribution check`** (`.github/workflows/ai-attribution.yml`) — fails any
  PR whose commits or description lack valid trailers. Tool-agnostic: another AI
  tool needs its own producer hook, or the fields get filled by hand.
- **`AI attribution audit`** (`.github/workflows/ai-attribution-audit.yml`) —
  post-merge backstop on every push to `master`. Opens an issue if unattributed
  commits land via an admin merge or a direct push, and fails the run.
- **`CI`** (`.github/workflows/ci.yml`) — the separate quality gate: graph
  validation, tests, coverage audit, build.

### Repository settings you must configure by hand

Workflow files cannot grant themselves authority. These are GitHub settings and
have to be set in the web UI:

1. **Ruleset on `master`** requiring `AI attribution check` and `CI` to pass
   before merge.
2. **Squash merge message** set to "pull request title and description", so the
   validated fields survive onto `master`.
3. Optionally **require linear history** or **signed commits** — signing is what
   makes the *human* identity cryptographically real, which attribution trailers
   alone do not.

Until step 1 is done, both workflows run and report but nothing blocks on them.

### What counts as a trailer

`trailer-block.sh` selects the **last blank-line-delimited paragraph containing
an `AI-` line**, rejoins folded values, and hands only that to the checks. Both
the commit check and the PR-body check use it, so a PR body and the squash commit
built from it are read identically.

Two decisions there are load-bearing, and both come from failures observed in the
original repo:

- **Not "scan the whole message."** Any prose quoting the trailer format becomes
  an indistinguishable trailer, so a documentation change describing this policy
  fails its own check. This file would be an example.
- **Not "the last paragraph."** GitHub builds the squash message from the PR
  body, and review bots append their notes *after* the author's content, so real
  trailers routinely sit well above the end.

Known limit, accepted: a message that quotes the format but carries no real
trailers has its example selected as the block. The example must then pass the
same value checks, and the PR template puts the real block last, so this is not
worth more machinery.

### Exemptions

- **Merge commits** — no authored change of their own.
- **`[bot]` authors and bot-authored PRs** — upgrade bots build their PR body
  from a changelog, ignore `PULL_REQUEST_TEMPLATE.md`, and cannot emit trailers.
  The bot identity in the author field is the attribution.
- **Commits at or before `5c262d6`** — the history that predates this policy,
  which used a `Co-Authored-By` / `Claude-Session` convention. Set via
  `AI_ATTRIBUTION_SINCE` in `check-commits.sh`. Without a boundary, adopting the
  check would flag the entire existing history on its first run.

## Transcript archiving (not yet ported)

The original policy includes a transcript-upload subsystem — pluggable `file` /
`github` / `s3` / `azure` backends, archiving on session end and after every
`git commit`, and a prefix-anchored secret scanner that refuses to upload a
transcript containing credentials.

That is deliberately **not** ported yet, for a specific reason rather than as an
oversight: sessions on this repository run in a remote container that is
reclaimed after inactivity, so a `file` backend would produce `AI-Transcript`
trailers pointing at paths that no longer exist — worse than omitting the field,
because it looks resolvable. Doing this properly here means the `github` backend
against a private transcripts repo, which is an account-level decision.

Consequences while it is missing:

- `AI-Transcript` is optional in both checkers. `AI-Model` and `AI-Session` are
  required.
- The audit trail is weaker than in `stock-analyzer`. Trailers can be verified as
  present and well-formed, but there is no archived transcript to check a claim
  against.
- **The secret-scanning rationale still applies** and is worth reading before
  turning archiving on: this policy requires a transcript per commit, and
  transcripts capture whatever was typed into a session, so a credential pasted
  mid-session flows into a long-lived archive by design.

## Caveats & trust model

- CI can enforce that metadata is **present and well-formed**, not that it is
  **true**. A determined developer can hand-type trailers. The audit trail is
  what makes lying detectable — which is why the archiving gap above matters.
- Archive destinations must be private and access-controlled. Never a public
  bucket, never a secret gist (readable by anyone with the URL), never Actions
  artifacts (they expire).
- If the model is switched mid-session, the state file keeps the session's
  starting model; the transcript remains the source of truth.
- `CLAUDECODE` / `CLAUDE_CODE_SESSION_ID` are exported by current Claude Code
  versions but are not formally documented. If they are ever absent, commits fall
  back to `AI-Assisted: none` and the CI check forces a human correction.

## Differences from stock-analyzer

| Aspect | stock-analyzer | Here | Why |
|---|---|---|---|
| Transcript archiving | Full subsystem with secret scanning | Not ported | Ephemeral container makes a local path a false reference; see above |
| `AI-Transcript` | Enforced | Optional | Follows from the above |
| Review gate | CodeRabbit status required | None | Installing a third-party app is an account decision, not a file change |
| Dependency updates | Renovate over pip + actions | Renovate over actions only | This project has no dependencies; only the workflow actions can drift |
| Python deps | `requirements.txt`, `pytest` | None | Stdlib-only is a deliberate design choice here |
| Grandfather boundary | n/a | `5c262d6` | Existing history used the older trailer convention |
