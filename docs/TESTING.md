# Testing

## Boundaries

Two real I/O boundaries, each mocked at its own seam, nowhere deeper:

- **Voyager/HTTP** (`auth.py`, `transport.py`, `browser.py`, `client.py`) —
  tests mock `transport._request`, `requests`/httpx call sites, and
  `LinkedInBrowserFallback`'s Playwright calls. Never a real HTTP request.
- **CDP** (`cdp_session.py`, `messaging.py`, `post_cdp.py`, `doctor.py`,
  `scan`-equivalent code) — tests mock `own_chrome.cdp.evaluate`/`.navigate`/
  `.describe`/`.pages`/`.filter_pages`/`.pick_page` and the raw `socket`
  module used by `CdpSession`. `tests/conftest.py`'s `_block_real_sockets`
  autouse fixture makes any test that forgets this fail loudly instead of
  silently touching a real Chrome.

Pure logic (`classify.py`, `copywriter.py`, `governor.py`, `guard.py`,
`agent_config.py`/`voyager_config.py` parsing, `post_cdp.lint_post`) is
tested directly with no mocking.

No test is skipped or marked `xfail`; a red test means something is broken.

## Run

```bash
uv run pytest -q --cov=linkedin_mcp --cov-report=term-missing
```

Run it three times before trusting a new/changed test — flakes hide in CDP
timing code (`auth_capture.capture`'s poll loop, `messaging.send_message`'s
verify-retry loop) if `time.sleep` isn't mocked.

Target: **>=80% line coverage on new/changed files** (all of `core.py`,
`guard.py`, `cli.py`, `mcp_server.py`, `auth_capture.py`, and every module
ported from linkedin-agent are at 85-100%); repo total should not drop below
what it was before a change.

## What's covered

- `guard.py` / `core.py` — the confirm gate on every Voyager write, and thin
  passthrough for every read, with a fake client (no real `LinkedInClient`).
- `mcp_server.py` — tool discovery (`list_tools`), a read tool round-tripping
  a dataclass to JSON, and the confirm guard surfacing as
  `UnexpectedToolError` when a write tool is called without `confirm: true`.
- `tests/test_mcp_parity.py` — every CLI command has a matching MCP tool
  (dashes/spaces -> underscores) or is on the explicit allowlist (`serve`,
  `auth_env`), and vice versa. This is the test that fails first if the two
  surfaces drift.
- `auth_capture.py` — the CDP cookie-capture poll loop (success, timeout,
  Chrome-not-reachable, and the raw `Network.getCookies` call), and that a
  cookie value never appears in the returned report.
- `agent_config.py`, `classify.py`, `copywriter.py`, `governor.py`,
  `messaging.py`, `referral.py`, `post_cdp.py`, `doctor.py`, `cdp_session.py`
  — ported from linkedin-agent with their full existing test suites,
  including the `SendNotConfirmedError` guard (function-level and
  CLI-level), Hypothesis property tests (`test_properties.py`), and an
  edge-string table (`test_edge_strings.py`: empty/unicode/emoji/injection-
  shaped/very-long input) run against every text-accepting pure function.
- `tests/test_ledger.py` — shared referral ledger: missing/empty/malformed
  file (raises, never overwritten), atomic append, dedupe, same-company
  match, unicode, exclusion regex. `JOE_REFERRAL_LEDGER` points tests at a
  temp file; no test touches `~/.config/joe-referral`.
- `tests/test_classify.py` — also `classify()` and `joe_fit()` (skip /
  stretch / strong table). `tests/test_scan_ledger.py` — scan with an
  injected fake reader plus ledger/exclusion rules and JSON output.
- `tests/test_compact.py` — token-minimal output: compact JSON, `--fields`
  / `--limit` / `--max-chars` (before and after the subcommand), truncation
  with unicode, `{"more":k}`, one-line errors, `scan` text keeps the newest
  chars, `-h` on nested commands. Core is mocked; no browser.
- `tests/test_mut_messaging.py` mocks the pinned-tab path (`pages` returning a
  tab with `webSocketDebuggerUrl`, `evaluate_pinned(ws_url, script)`), not
  `evaluate`; `send_message` re-checks `location.href` before clicking Send.
- `tests/test_cli_help.py` — `-h` and `--help` on the root, each command group, and a leaf command. `--json` / `-j` shows up on `messages read -h`.
- `tests/test_cli_messaging_url_race.py` — every CLI command and flag that
  opens messaging (`scan`, `messages open|threads|select|read|popups|send
  --to`, including `--json`, `--unread`, `--limit`, `--filter`,
  `--no-navigate`). Chrome's tab list still showing the feed URL after
  `Page.navigate` must not raise `No open tab URL contains
  'https://www.linkedin.com/messaging/'`. The readiness poll is on the
  navigated tab's websocket; `scan` stops if that poll never sees the
  thread list.
- `client.py`, `transport.py`, `auth.py`, `browser.py`, `formatter.py`,
  `serialization.py`, `models.py`, `voyager_config.py` — unchanged from
  frizynn/linkedin-cli aside from the import path; their existing coverage
  carries over as-is.

## Not covered on purpose

- `own_chrome.cdp`'s own internals, and the `li` CLI it used to ship — out of
  scope; `li`-dependent code (`scan`/`li_cli`) was intentionally not ported
  (see README "absorbed" section) rather than tested against a stale seam.
- The real MCP stdio transport (`mcp.run(transport="stdio")`) — verified by
  hand with a real client (`ClientSession` + `stdio_client` against the
  installed `linkedin-mcp serve` binary), not in the automated suite, since
  it spawns a subprocess and talks a wire protocol rather than exercising a
  code path unit tests would catch differently.
