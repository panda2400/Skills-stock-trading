# Data Quality

Provider data must pass quality checks before it enters `stock-technical-analysis`.

## Required Checks

- Schema validation.
- Required field validation.
- Primary key dedupe by `symbol + date` or `date` for single-symbol files.
- Stable sorting by `symbol, date` or `date`.
- Date normalization to `YYYY-MM-DD`.
- Numeric normalization for OHLCV and realtime fields.
- Invalid OHLC detection:
  - negative prices
  - `high < low`
  - `close` outside `high/low`
  - missing OHLC fields
- Sample threshold:
  - fewer than 60 daily bars blocks full analysis
  - degraded sample emits a warning

## Empty Result Reasons

Do not say "接口坏了" for every empty table. Classify it first:

| Reason | Meaning |
|---|---|
| `non_trading_day` | Market was closed for the requested date. |
| `no_data_in_range` | Valid symbol and range, but no records. |
| `before_listing` | Requested range is before listing date. |
| `invalid_params` | Symbol, market, or date parameters are invalid. |
| `permission_denied` | Provider auth, quote card, OpenD, OAuth, token, or permission failure. |
| `unknown_empty` | Empty result with no reliable cause. |

## Report Behavior

- Quality failure: stop full analysis and report the specific failure.
- Benchmark missing: continue with qualitative RS fallback.
- Realtime missing: continue and state that trigger status is unavailable.
- Provider partial success: say which ranges succeeded and which failed.
