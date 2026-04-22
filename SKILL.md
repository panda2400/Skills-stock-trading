---
name: stock-trading-assistant
description: Read-only stock trading assistant for A-share and US equities. Use when the user asks for stock trading decision support, technical setup, realtime trigger status, A-share or US kline/quote collection, provider fallback across Futu/Longbridge/Tushare, data quality checks, cache-aware market data preparation, or orchestration of stock-technical-analysis. Produces conditional decision support only and must not place, modify, or cancel orders.
---

# Stock Trading Assistant

Use this top-level skill to orchestrate market-data providers and the deterministic `stock-technical-analysis` engine into a read-only trading decision-support workflow for A-share and US stocks.

## Core Rules

- Keep this skill read-only. Do not place, modify, cancel, unlock, or confirm orders.
- Use provider adapters for data acquisition; do not put provider-specific API logic in the technical analysis engine.
- Normalize all provider outputs to local CSV/JSON before analysis.
- Run data quality checks before calling `stock-technical-analysis`.
- Produce conditional decision support, not unconditional buy/sell instructions.
- Clearly state data gaps, cache usage, provider failures, and downgraded confidence.

## Workflow

1. Resolve the symbol and market.
   - A-share internal format: `600519.SH`, `000001.SZ`.
   - US internal format: `AAPL.US`, `TSLA.US`.
   - Ask only when the symbol is ambiguous.

2. Select provider.
   - Prefer Futu when OpenD is available and permissions are sufficient.
   - Use Longbridge as the AI-native fallback or when explicitly requested.
   - Use Tushare only for A-share research enrichment such as finance, valuation, capital flow, sectors, news, macro, or screening.

3. Fetch and normalize data.
   - Required: daily OHLCV CSV.
   - Optional: benchmark OHLCV CSV and realtime snapshot JSON.
   - Use cache when possible; fetch only missing date segments.

4. Validate data quality.
   - Schema, required fields, dedupe, sorting, date normalization, numeric normalization, invalid OHLC, and sample threshold checks are mandatory.
   - Empty data must be classified, not described generically as an interface failure.

5. Run analysis.
   - Call the existing `stock-technical-analysis/scripts/analyze.py`.
   - Call `stock-technical-analysis/scripts/render.py`.
   - Append realtime trigger status when `realtime_state.json` is available.

6. Deliver the report.
   - Keep language conditional: "若 A 成立，则 B 可观察".
   - Show cache provenance and data gaps.
   - Do not produce direct buy/sell commands.

## References

- [architecture](references/architecture.md): overall responsibilities and data flow.
- [provider-contract](references/provider-contract.md): provider methods, symbols, CSV/JSON contracts.
- [data-quality](references/data-quality.md): validation, empty-result classification, and report behavior.
- [cache-policy](references/cache-policy.md): file cache layout, incremental update, resume, naming.
- [host-adapters](references/host-adapters.md): Codex and Claude Code execution paths.
- [safety](references/safety.md): read-only safety boundary and banned operations.

## Scripts

- `scripts/run_analysis.py`: end-to-end orchestration.
- `scripts/normalize_ohlcv.py`: provider JSON to standard OHLCV CSV.
- `scripts/quality_check.py`: CSV and realtime JSON validation.
- `scripts/cache_manager.py`: file cache helpers and provenance.
- `scripts/symbol_map.py`: A-share/US symbol normalization.
- `scripts/providers/`: Futu, Longbridge, and Tushare adapters.

## Pre-Delivery Checklist

- Provider output was normalized to the standard contracts.
- Data quality checks passed or the failure was reported clearly.
- Empty results have an explicit reason.
- Cache provenance is visible.
- `stock-technical-analysis` was called only with local files.
- No trading script or order-placement tool was invoked.
- Final language is conditional decision support.
