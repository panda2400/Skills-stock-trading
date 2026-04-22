# Host Adapters

The same provider contract applies in Codex and Claude Code. Only the tool access path changes.

## Codex

- Use local filesystem, CLI, MCP, and existing checked-out skills.
- Write intermediate files to the workspace or `/tmp`.
- Do not assume GUI apps can be launched without approval.
- Prefer local fixture tests when provider credentials are absent.

## Claude Code

- Use installed Skills and MCP when available.
- Use Futu OpenD if already running.
- Use the same normalized CSV/JSON outputs as Codex.

## Shared Fallback Order

1. User-provided CSV/JSON.
2. Futu provider.
3. Longbridge provider.
4. Tushare research enrichment for A-share research requests.
5. Data-insufficient response.

Do not fabricate bars, quotes, earnings dates, or benchmark data.
