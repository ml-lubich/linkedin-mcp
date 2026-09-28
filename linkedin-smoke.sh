#!/usr/bin/env bash
# Smoke test for the local linkedin CLI (frizynn/linkedin-cli).
# Hits the real Voyager API with your real session — no mocks, no stubs.
# Exits non-zero on the first failure so it's CI/agent-usable.
#
# Usage:  export LINKEDIN_COOKIE_HEADER='li_at=...; JSESSIONID="ajax:..."; ...'
#         ./linkedin-smoke.sh
set -uo pipefail

BIN="$HOME/.local/bin/linkedin"
pass=0; fail=0

check() {  # check <name> <cmd...>
  local name="$1"; shift
  if out=$("$@" 2>&1); then
    echo "  ok   $name"; pass=$((pass+1))
  else
    echo "  FAIL $name"
    echo "$out" | sed 's/^/         /' | head -6
    fail=$((fail+1))
  fi
}

echo "linkedin-cli smoke test"

# 0. Preconditions — fail fast with a real reason, not a confusing API error.
[ -x "$BIN" ] || { echo "  FAIL binary missing at $BIN"; exit 1; }
if [ -z "${LINKEDIN_COOKIE_HEADER:-}${LINKEDIN_LI_AT:-}" ]; then
  echo "  FAIL no session configured."
  echo "       export LINKEDIN_COOKIE_HEADER='li_at=...; JSESSIONID=\"ajax:...\"; ...'"
  echo "       (Chrome 127+ app-bound encryption breaks the auto-extraction fallback.)"
  exit 1
fi

# 1. Session is live. Everything else is meaningless if this fails.
check "auth-status"        "$BIN" auth-status

# 2. Read path — the part the README calls verified end-to-end.
check "feed --json"        "$BIN" feed --max 3 --json
check "profile (self)"     "$BIN" profile "$(id -un)" --json
check "search --json"      "$BIN" search "engineer" --max 3 --json

# Write ops (post/react/comment) are deliberately NOT smoke-tested:
# they mutate your real account and are the ops that carry ban risk.

echo "---"
echo "passed: $pass  failed: $fail"
[ "$fail" -eq 0 ]
