#!/usr/bin/env python3
"""Symbol normalization helpers for A-share and US stocks."""

from __future__ import annotations

import argparse
import json
import re


class SymbolError(ValueError):
    pass


def normalize_symbol(raw: str, default_market: str | None = None) -> str:
    value = (raw or "").strip().upper()
    if not value:
        raise SymbolError("empty symbol")

    value = value.replace(" ", "")

    # Futu style: SH.600519, SZ.000001, US.AAPL
    if re.match(r"^(SH|SZ)\.\d{6}$", value):
        prefix, code = value.split(".", 1)
        return f"{code}.{prefix}"
    if re.match(r"^US\.[A-Z0-9.-]+$", value):
        _, code = value.split(".", 1)
        return f"{code}.US"

    # Canonical/Longbridge style: 600519.SH, AAPL.US
    if re.match(r"^\d{6}\.(SH|SZ)$", value):
        return value
    if re.match(r"^[A-Z0-9.-]+\.US$", value):
        return value

    # Bare A-share code.
    if re.match(r"^\d{6}$", value):
        if value.startswith(("6", "5", "9")):
            return f"{value}.SH"
        if value.startswith(("0", "1", "2", "3")):
            return f"{value}.SZ"
        raise SymbolError(f"unsupported A-share prefix: {value}")

    # Bare US ticker.
    if re.match(r"^[A-Z][A-Z0-9.-]{0,9}$", value):
        market = (default_market or "US").upper()
        if market != "US":
            raise SymbolError(f"bare ticker requires US market, got {market}")
        return f"{value}.US"

    raise SymbolError(f"unsupported symbol format: {raw}")


def market_of(symbol: str) -> str:
    canonical = normalize_symbol(symbol)
    if canonical.endswith((".SH", ".SZ")):
        return "A"
    if canonical.endswith(".US"):
        return "US"
    raise SymbolError(f"unsupported market: {symbol}")


def to_futu(symbol: str) -> str:
    canonical = normalize_symbol(symbol)
    code, market = canonical.split(".", 1)
    if market in ("SH", "SZ"):
        return f"{market}.{code}"
    if market == "US":
        return f"US.{code}"
    raise SymbolError(f"unsupported Futu market: {market}")


def to_longbridge(symbol: str) -> str:
    return normalize_symbol(symbol)


def to_analysis_ticker(symbol: str) -> str:
    canonical = normalize_symbol(symbol)
    code, market = canonical.split(".", 1)
    return code if market in ("SH", "SZ") else code


def analysis_market(symbol: str) -> str:
    return market_of(symbol)


def display_symbol(symbol: str) -> str:
    canonical = normalize_symbol(symbol)
    code, market = canonical.split(".", 1)
    return code if market in ("SH", "SZ") else code


def benchmark_symbol(symbol_or_market: str) -> str:
    raw = (symbol_or_market or "").upper()
    market = raw if raw in ("A", "US") else market_of(raw)
    return "000300.SH" if market == "A" else "SPY.US"


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize stock symbols")
    parser.add_argument("symbol")
    parser.add_argument("--format", choices=["canonical", "futu", "longbridge", "analysis", "market", "benchmark"],
                        default="canonical")
    args = parser.parse_args()

    if args.format == "canonical":
        value = normalize_symbol(args.symbol)
    elif args.format == "futu":
        value = to_futu(args.symbol)
    elif args.format == "longbridge":
        value = to_longbridge(args.symbol)
    elif args.format == "analysis":
        value = to_analysis_ticker(args.symbol)
    elif args.format == "market":
        value = market_of(args.symbol)
    else:
        value = benchmark_symbol(args.symbol)

    print(json.dumps({"input": args.symbol, "value": value}, ensure_ascii=False))


if __name__ == "__main__":
    main()
