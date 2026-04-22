# Architecture

`stock-trading-assistant` is an orchestration skill, not a replacement for the provider skills or the technical analysis engine.

## Responsibilities

| Layer | Responsibility |
|---|---|
| Provider adapters | Fetch raw market or research data from Futu, Longbridge, or Tushare. |
| Normalization | Convert provider output into standard CSV/JSON contracts. |
| Cache | Reuse stable data and fetch only missing ranges. |
| Quality check | Block bad data before analysis. |
| Technical engine | Run `stock-technical-analysis` on local files. |
| Assistant | Explain conditional setups, realtime trigger status, cache provenance, and gaps. |

## Data Flow

```text
User request
  -> symbol_map
  -> provider healthcheck
  -> provider raw JSON
  -> normalize_ohlcv
  -> cache_manager
  -> quality_check
  -> stock-technical-analysis/analyze.py
  -> stock-technical-analysis/render.py
  -> realtime trigger appendix
  -> final read-only report
```

## Provider Roles

- Futu: primary A-share provider when OpenD and permissions are available; also supports US.
- Longbridge: fallback and AI-native provider through CLI/MCP/SDK; supports A-share and US subject to account permissions.
- Tushare: A-share research enrichment for finance, valuation, capital flow, sectors, news, macro, and screening.

## Non-Goals In MVP

- No order placement.
- No portfolio execution.
- No database.
- No always-on realtime monitor.
- No replacement of `stock-technical-analysis` internals.
