# Cache Policy

MVP uses file cache, not a database.

## Cache Roots

```text
cache/
├── base/
├── history/
├── realtime/
└── meta/
```

## Cacheable Data

- Symbol basics.
- Trading calendars.
- Index basics.
- Benchmark history.
- Daily and weekly kline data.
- Last realtime snapshot.

## Incremental Update

1. Find cached files covering the requested symbol, period, and date range.
2. If fully covered, reuse cache.
3. If partially covered, fetch only missing segments.
4. Merge, dedupe, sort, and re-run quality checks.
5. Save provenance metadata.

## Resume

Each successful segment writes metadata under `cache/meta/`. On retry, skip successful segments and only fetch missing or failed segments.

## Naming

```text
daily_600519.SH_20230101_20231231_20260421.csv
weekly_AAPL.US_20240101_20260421_20260421.csv
benchmark_SPY.US_20240101_20260421_20260421.csv
realtime_600519.SH_20260421T103215.json
fina_indicator_300750.SZ_20260421.parquet
```

## Disclosure

Reports or logs should state which data came from cache and which data was newly fetched.
