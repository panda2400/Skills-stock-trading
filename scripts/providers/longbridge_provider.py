#!/usr/bin/env python3
"""Read-only adapter for Longbridge CLI/MCP/SDK outputs.

The adapter keeps Longbridge behind the same JSON/CSV contract used by Futu.
Live invocation uses command templates so the Skill can work with either a CLI
installation or a host-provided MCP wrapper without hard-coding account details.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from symbol_map import benchmark_symbol, market_of, normalize_symbol, to_longbridge


DENIED_ORDER_TERMS = {"submit_order", "place_order", "replace_order", "cancel_order", "order"}


class ProviderError(RuntimeError):
    def __init__(self, message: str, reason: str = "unknown_empty", raw_summary: str | None = None):
        super().__init__(message)
        self.reason = reason
        self.raw_summary = raw_summary or message


def healthcheck() -> dict[str, Any]:
    cli = os.environ.get("LONGBRIDGE_CLI") or "longbridge"
    return {
        "provider": "longbridge",
        "cli": cli,
        "cli_found": shutil.which(cli) is not None,
        "kline_template_configured": bool(os.environ.get("LONGBRIDGE_KLINE_CMD")),
        "snapshot_template_configured": bool(os.environ.get("LONGBRIDGE_SNAPSHOT_CMD")),
        "read_only": True,
        "denied_order_terms": sorted(DENIED_ORDER_TERMS),
    }


def resolve_symbol(symbol: str) -> dict[str, str]:
    canonical = normalize_symbol(symbol)
    return {"symbol": canonical, "provider_symbol": to_longbridge(canonical), "market": market_of(canonical)}


def _classify_error(text: str) -> str:
    lower = text.lower()
    if any(token in lower for token in ("permission", "unauthorized", "forbidden", "token", "scope")):
        return "permission_denied"
    if any(token in lower for token in ("invalid", "bad parameter", "unknown symbol", "参数")):
        return "invalid_params"
    return "unknown_empty"


def _command_from_template(template: str, values: dict[str, str]) -> list[str]:
    rendered = template.format(**values)
    lowered = rendered.lower()
    if any(term in lowered for term in DENIED_ORDER_TERMS):
        raise ProviderError(f"Longbridge order-capable command is denied: {rendered}", reason="invalid_params")
    return shlex.split(rendered)


def _run_json(command: list[str]) -> Any:
    lowered = " ".join(command).lower()
    if any(term in lowered for term in DENIED_ORDER_TERMS):
        raise ProviderError(f"Longbridge order-capable command is denied: {' '.join(command)}", reason="invalid_params")
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    output = (completed.stdout or "").strip()
    if completed.returncode != 0:
        raw = (completed.stderr or completed.stdout or "").strip()
        raise ProviderError(f"Longbridge command failed: {raw}", reason=_classify_error(raw), raw_summary=raw[:500])
    try:
        payload = json.loads(output or "{}")
    except json.JSONDecodeError as exc:
        raise ProviderError(f"Longbridge returned non-JSON output: {output[:300]}", raw_summary=output[:500]) from exc
    if isinstance(payload, dict) and payload.get("error"):
        message = str(payload["error"])
        raise ProviderError(message, reason=_classify_error(message), raw_summary=message[:500])
    return payload


def _records_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, list):
        return data
    for key in ("items", "klines", "candles"):
        if isinstance(payload.get(key), list):
            return payload[key]
    return []


def _normalize_trade_date(value: Any, market: str) -> str:
    text = str(value or "").strip().replace("/", "-")
    if not text:
        return text
    if len(text) >= 19 and text[10] == " ":
        try:
            timestamp = dt.datetime.fromisoformat(text[:19])
        except ValueError:
            return text[:10]
        if market == "A":
            timestamp += dt.timedelta(hours=8)
        return timestamp.date().isoformat()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return text[:10]


def _normalize_volume(value: Any, market: str) -> Any:
    if value in (None, ""):
        return value
    try:
        numeric = float(str(value).replace(",", ""))
    except ValueError:
        return value
    if market == "A":
        numeric *= 100
    return int(numeric) if numeric.is_integer() else numeric


def _normalize_kline_records(records: list[dict[str, Any]], market: str) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in records:
        item = dict(row)
        item["date"] = _normalize_trade_date(item.get("date") or item.get("time") or item.get("timestamp"), market)
        item["volume"] = _normalize_volume(item.get("volume"), market)
        normalized.append(item)
    return normalized


def get_history_kline(symbol: str, start: str, end: str, period: str = "day") -> dict[str, Any]:
    resolved = resolve_symbol(symbol)
    values = {"symbol": resolved["provider_symbol"], "start": start, "end": end, "period": period}
    template = os.environ.get("LONGBRIDGE_KLINE_CMD")
    if template:
        command = _command_from_template(template, values)
    else:
        cli = os.environ.get("LONGBRIDGE_CLI") or "longbridge"
        command = [
            cli,
            "kline",
            "history",
            resolved["provider_symbol"],
            "--start",
            start,
            "--end",
            end,
            "--period",
            period,
            "--format",
            "json",
        ]
    raw_payload = _run_json(command)
    payload = {
        "symbol": resolved["symbol"],
        "provider_symbol": resolved["provider_symbol"],
        "provider": "longbridge",
        "data": _normalize_kline_records(_records_from_payload(raw_payload), resolved["market"]),
    }
    if not payload["data"]:
        payload["empty_reason"] = raw_payload.get("empty_reason") if isinstance(raw_payload, dict) else "unknown_empty"
    return payload


def get_snapshot(symbols: list[str]) -> list[dict[str, Any]]:
    states: list[dict[str, Any]] = []
    template = os.environ.get("LONGBRIDGE_SNAPSHOT_CMD")
    cli = os.environ.get("LONGBRIDGE_CLI") or "longbridge"
    now = dt.datetime.now().isoformat(timespec="seconds")
    for symbol in symbols:
        resolved = resolve_symbol(symbol)
        values = {"symbol": resolved["provider_symbol"]}
        if template:
            command = _command_from_template(template, values)
        else:
            command = [cli, "quote", resolved["provider_symbol"], "--format", "json"]
        payload = _run_json(command)
        row = payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), dict) else payload
        if isinstance(row, list):
            row = row[0] if row else {}
        if not isinstance(row, dict) or not row:
            continue
        states.append({
            "symbol": resolved["symbol"],
            "market": resolved["market"],
            "provider": "longbridge",
            "timestamp": row.get("timestamp") or row.get("time") or now,
            "last": row.get("last") or row.get("last_done") or row.get("price") or row.get("last_price"),
            "open": row.get("open"),
            "high": row.get("high"),
            "low": row.get("low"),
            "volume": _normalize_volume(row.get("volume"), resolved["market"]),
            "turnover": row.get("turnover"),
            "bid": row.get("bid"),
            "ask": row.get("ask"),
            "prev_close": row.get("prev_close") or row.get("prev_close_price"),
        })
    return states


def get_benchmark(symbol: str, start: str, end: str) -> dict[str, Any]:
    return get_history_kline(benchmark_symbol(symbol), start=start, end=end, period="day")


def main() -> None:
    parser = argparse.ArgumentParser(description="Longbridge read-only provider adapter")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("healthcheck")

    resolve_p = sub.add_parser("resolve")
    resolve_p.add_argument("symbol")

    kline_p = sub.add_parser("kline")
    kline_p.add_argument("symbol")
    kline_p.add_argument("--start", required=True)
    kline_p.add_argument("--end", required=True)
    kline_p.add_argument("--period", default="day")

    snap_p = sub.add_parser("snapshot")
    snap_p.add_argument("symbols", nargs="+")

    args = parser.parse_args()
    try:
        if args.command == "healthcheck":
            result = healthcheck()
        elif args.command == "resolve":
            result = resolve_symbol(args.symbol)
        elif args.command == "kline":
            result = get_history_kline(args.symbol, args.start, args.end, period=args.period)
        elif args.command == "snapshot":
            result = {"data": get_snapshot(args.symbols)}
        else:
            raise AssertionError(args.command)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except ProviderError as exc:
        print(json.dumps({"status": "error", "reason": exc.reason, "message": str(exc), "raw_summary": exc.raw_summary}, ensure_ascii=False))
        raise SystemExit(2)


if __name__ == "__main__":
    main()
