# Write Workflows

## Contents

1. Preflight
2. Command matrix
3. Identifier handling
4. Browser fallback behavior
5. Failure mapping
6. Safety rules

## Preflight

Always verify the session first:

```bash
uv run linkedin auth-status
```

If the result is degraded, stop and repair auth before posting, reacting, or commenting.

## Command Matrix

Every command below **requires `--confirm`** (added in linkedin-mcp; the
original linkedin-mcp had no gate on these). Without it, `ConfirmRequiredError`
refuses the action before it reaches the client at all — nothing is touched.

Publish a post:

```bash
uv run linkedin post "hello from linkedin-mcp" --confirm
uv run linkedin post "hello from linkedin-mcp" --visibility public --confirm
```

React to an activity:

```bash
uv run linkedin react urn:li:activity:123 --type like --confirm
uv run linkedin react urn:li:activity:123 --type celebrate --confirm
uv run linkedin react urn:li:activity:123 --type support --confirm
uv run linkedin react urn:li:activity:123 --type love --confirm
uv run linkedin react urn:li:activity:123 --type insightful --confirm
uv run linkedin react urn:li:activity:123 --type curious --confirm
```

Remove the current reaction:

```bash
uv run linkedin unreact urn:li:activity:123 --confirm
```

Save or unsave an activity:

```bash
uv run linkedin save urn:li:activity:123 --confirm
uv run linkedin unsave urn:li:activity:123 --confirm
```

Comment on an activity:

```bash
uv run linkedin comment urn:li:activity:123 "nice post" --confirm
```

## Identifier Handling

Write-side commands accept:

- a full activity URN
- a numeric activity id
- a full LinkedIn activity URL

Normalize unknown activity references before mutating them. If needed, inspect them first with:

```bash
uv run linkedin activity <identifier> --json
```

## Browser Fallback Behavior

Current implementation details:

- `post` uses Playwright-backed browser fallback
- `comment` uses Playwright-backed browser fallback
- `save` and `unsave` use Playwright-backed browser fallback
- `unreact` uses Playwright-backed browser fallback
- `react` uses the API client directly

Important limitation:

- browser fallback only supports applying `like` directly when it is used as the fallback path
- richer reactions depend on the normal API flow succeeding

If Playwright browsers are missing, install them from the repository root:

```bash
uv run playwright install chromium
```

## Failure Mapping

`Unsupported reaction type`

- Use one of: `like`, `celebrate`, `support`, `love`, `insightful`, `curious`

`Unsupported LinkedIn activity identifier`

- Convert the value to a numeric activity id, a full URN, or a LinkedIn activity URL

`Unable to locate LinkedIn UI control`

- LinkedIn UI selectors likely changed or the session is not landing on the expected page
- verify `auth-status`
- retry with a healthy browser-backed session

`Playwright is not installed`

- Install project dependencies and Playwright browser binaries before retrying

## Safety Rules

- Never pass `--confirm` unless the current turn explicitly named the exact target and text.
- Treat all write operations as user-facing side effects.
- Do not post, react, save, or comment in bulk.
- Do not log secrets or browser cookies while debugging write failures.
- Confirm `public` visibility explicitly; otherwise prefer `connections`.
