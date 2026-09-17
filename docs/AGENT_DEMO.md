# Agent demo — Claude Desktop over the local MCP server

This is the "UI" for the agent, on purpose (see `docs/DECISIONS.md`): SPEC.md
Part 3 scopes out any user-facing UI beyond a CLI and a demo notebook, and any
MCP client can drive `src/server.py` for free. Claude Desktop is used here as
that MCP client — no additional code, no hosting, no auth.

## 1. Point Claude Desktop at the server

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (create
it if it doesn't exist) and add an entry under `mcpServers`:

```json
{
  "mcpServers": {
    "procurement-resolver": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/Users/adamkaegi/Documents/GitHub/procurement-resolver",
        "python",
        "-m",
        "src.server"
      ]
    }
  }
}
```

If the file already has other `mcpServers` entries, add
`"procurement-resolver"` alongside them rather than replacing the file.

Fully quit and reopen Claude Desktop (not just close the window) for it to
pick up the config. Confirm it connected: the tool/plug icon in a new chat
should list `resolve_vendor`, `entity_profile`, `cross_level_exposure`,
`compare_buyers`, and `coverage` under "procurement-resolver".

The server opens the warehouse **read-only** on every call, so it's safe to
run alongside a `duckdb data/warehouse.duckdb` CLI session browsing the same
file — though if that CLI session was opened in its default read-write mode,
it holds an exclusive lock DuckDB doesn't let readers share (see "Known
friction" below).

Run `uv run python scripts/rebuild.py` first if `data/warehouse.duckdb`
doesn't exist yet — the server raises a clear error naming that command if
the file is missing.

## 2. A two-part demo in one session (success criterion 4)

Ask both of these in the same conversation, back to back.

**Part A — answerable, confidence attached.**
> Resolve "Bell Canada" and tell me its total contract exposure across
> jurisdictions.

Expect: `resolve_vendor` returns ranked candidates scored by the blocking
index, exact matches first. Picking the right entity and calling `cross_level_exposure`
should return `declined: false` with a real per-jurisdiction breakdown,
including a federal source where some included contracts are $0 and
explicitly excluded from the total rather than silently zeroed.

**Part B — correctly declines (the bucket-C moment).**
> Resolve "Kleenoil Filtration Canada Ltd" and give me its cross-level
> exposure.

Expect: `cross_level_exposure` returns `declined: true` with the reason
("resolves to records in only 1 jurisdiction") and still shows the
single-source detail instead of fabricating a cross-level number. This is
the pairing the whole project is built to demonstrate — a real answer with
confidence, and a real refusal with a stated reason, in one sitting.

A third prompt worth having ready if there's time:
> What jurisdictions and date ranges does this system actually cover, and
> what are the known gaps?

This calls `coverage` directly and surfaces the $10K/$25K threshold
differences and the documented known_gaps per source (Ontario VOR's
zero-value arrangements, Ottawa's multi-vendor roster rows, the federal 5,000-row
truncation) — the thing spec Part 2 calls "the best argument in the project
for why an agent with coverage awareness beats a dashboard."

## Known friction

- **DuckDB single-writer lock.** If you have `duckdb data/warehouse.duckdb`
  open in another terminal in its default (read-write) mode, it holds an
  exclusive lock and the MCP server's read-only connections will fail with
  `IO Error: Could not set lock on file...`. Either close that session, or
  reopen it read-only: `duckdb data/warehouse.duckdb -readonly`.
- **Unadjudicated candidates are shown but never counted.** Entities may
  carry uncertain-band (0.65-0.92) `candidate_links`. `entity_profile`
  lists them and `cross_level_exposure` notes them, but they are excluded
  from every contract list, jurisdiction count, and dollar total until
  adjudicated — so a profile can legitimately show candidates alongside a
  total that ignores them.
