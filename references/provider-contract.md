# Provider Contract

All providers must output the same local contracts regardless of host or backend.

## Symbol Formats

Internal canonical format:

- A-share: `600519.SH`, `000001.SZ`
- US: `AAPL.US`, `TSLA.US`

Provider conversion:

| Provider | A-share | US |
|---|---|---|
| Futu | `SH.600519`, `SZ.000001` | `US.AAPL` |
| Longbridge | `600519.SH`, `000001.SZ` | `AAPL.US` |
| Technical report display | `600519`, `000001` | `AAPL` |

## Required Provider Methods

- `healthcheck()`: return availability, auth status, and permission hints.
- `resolve_symbol(query)`: return canonical symbol and market.
- `get_history_kline(symbol, period, start, end, adjust)`: return raw provider kline JSON.
- `get_snapshot(symbols)`: return raw provider snapshot JSON.
- `get_benchmark(market, start, end)`: return benchmark kline JSON.
- `get_calendar(market, start, end)`: optional trading calendar lookup.

## Standard OHLCV CSV

Columns:

```text
date,open,high,low,close,volume
```

Rules:

- `date` is `YYYY-MM-DD`.
- Rows are sorted ascending by date.
- Numeric columns are normalized before analysis.
- Daily data needs at least 60 bars for full analysis.

## Realtime State JSON

Required fields:

- `symbol`
- `market`
- `provider`
- `timestamp`
- `last`

Optional fields:

- `open`
- `high`
- `low`
- `volume`
- `turnover`
- `bid`
- `ask`
- `prev_close`
- `source_latency_ms`

## Provider Error Contract

Provider errors should include:

- `provider`
- `operation`
- `symbol`
- `status`
- `empty_reason` when data is empty
- `raw_error` or short raw provider summary when useful
