# Changelog

All notable changes to this project should be documented in this file.

The format is based on Keep a Changelog, adapted for this repository.

## [Unreleased]

- Token-minimal CLI: every read command prints one line of compact JSON; global
  `--fields`, `--limit`, `--max-chars` (default 300); one-line errors with the
  next step (`linkedin_mcp/compact.py`); write commands print one status line.
  `--json` is accepted and a no-op. `messages threads --filter` with no match
  now exits 2 with or without `--json`.
- `linkedin scan` prints `scan.to_json` (compact, with `fit`); `core.classify_message`
  now returns `classify()`'s `{hiring, excluded, already_referred, reason}`
  (`exclude_reason` is gone, use `reason`).
- Fixed the 9 stale `tests/test_mut_messaging.py` tests: they now mock the real
  pinned-tab path (`pages` + `evaluate_pinned`). The tab-collision test became
  "never picks a tab whose URL merely embeds the messaging URL".
- New agent skill `~/.claude/skills/linkedin/SKILL.md`.
- Added `ledger.py`: the shared Joe-referral ledger (email + LinkedIn), atomic
  appends, dedupe by email/profile URL, loud failure on malformed JSON, and the
  shared exclusion regex.
- `classify.classify()` returns `{hiring, excluded, already_referred, reason}`
  using the ledger; new deterministic `classify.joe_fit()` honesty guard.
- `scan` applies the ledger/exclusion/last-speaker/referee rules, takes an
  injectable page reader, and `scan.to_json` prints JSON candidates with fit.

## [0.2.0] - 2026-09-27

Renamed `linkedin-cli` to `linkedin-mcp` and absorbed `linkedin-agent`.

Highlights:
- Migrated the CLI from Click to Typer (`linkedin`/`linkedin-mcp` scripts)
- Added an MCP server (`linkedin-mcp serve`) exposing every command as a tool
  from a shared core, with a parity test that fails if the two drift apart
- Added a confirm gate (`--confirm` / `confirm: true`) to the previously
  ungated Voyager writes (`post`, `react`, `unreact`, `save`, `unsave`, `comment`)
- Absorbed linkedin-agent's CDP surface: `doctor`, `classify`, `post-cdp`,
  `messages`, `referral`, governor-paced rate limiting
- Added CDP-based session cookie capture (`linkedin auth capture`/`auth env`),
  replacing browser-cookie3 extraction for Chrome 127+'s encrypted cookie DB
- Merged three Codex skills into one (`skills/linkedin-mcp/`)

## [0.1.0] - 2026-03-09

Initial open-source release.

Highlights:
- Added a Python-based LinkedIn CLI package with Click commands
- Added authenticated feed, profile, search, activity, and profile-posts flows
- Added browser-assisted write flows for posting, reacting, saving, and commenting
- Added support for `LINKEDIN_COOKIE_HEADER`, minimal env cookies, and browser cookie extraction
- Added auth diagnostics and direct Voyager transport
- Added tests, CI workflow, and publish workflow
