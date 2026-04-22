#!/usr/bin/env python3
"""Quality checks for normalized OHLCV CSV and realtime JSON."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
from pathlib import Path
from typing import Any


REQUIRED_OHLCV = ("date", "open", "high", "low", "close", "volume")
REQUIRED_REALTIME = ("symbol", "market", "provider", "timestamp", "last")
EMPTY_REASONS = {
    "non_trading_day",
    "no_data_in_range",
    "before_listing",
    "invalid_params",
    "permission_denied",
    "unknown_empty",
}


class QualityError(ValueError):
    def __init__(self, errors: list[str], warnings: list[str] | None = None):
        super().__init__("; ".join(errors))
        self.errors = errors
        self.warnings = warnings or []


def normalize_date(value: Any) -> str:
    text = str(value or "").strip().replace("/", "-")
    if len(text) == 8 and text.isdigit():
        text = f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    try:
        return dt.date.fromisoformat(text[:10]).isoformat()
    except ValueError as exc:
        raise ValueError(f"invalid date {value!r}") from exc


def normalize_number(value: Any, field: str) -> float:
    if value is None or value == "":
        raise ValueError(f"missing {field}")
    return float(str(value).replace(",", ""))


def read_and_clean_ohlcv(path: str | Path, min_bars: int = 60) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    source = Path(path)
    with source.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = set(reader.fieldnames or [])
        missing = [field for field in REQUIRED_OHLCV if field not in columns]
        if missing:
            raise QualityError([f"missing columns: {', '.join(missing)}"])

        errors: list[str] = []
        warnings: list[str] = []
        by_date: dict[str, dict[str, Any]] = {}
        duplicate_count = 0
        raw_count = 0

        for index, row in enumerate(reader, start=2):
            raw_count += 1
            try:
                cleaned = {
                    "date": normalize_date(row.get("date")),
                    "open": normalize_number(row.get("open"), "open"),
                    "high": normalize_number(row.get("high"), "high"),
                    "low": normalize_number(row.get("low"), "low"),
                    "close": normalize_number(row.get("close"), "close"),
                    "volume": normalize_number(row.get("volume"), "volume"),
                }
                if any(cleaned[field] < 0 for field in ("open", "high", "low", "close")):
                    raise ValueError("negative price")
                if cleaned["high"] < cleaned["low"]:
                    raise ValueError("high < low")
                if not (cleaned["low"] <= cleaned["close"] <= cleaned["high"]):
                    raise ValueError("close outside high/low")
                if cleaned["date"] in by_date:
                    duplicate_count += 1
                by_date[cleaned["date"]] = cleaned
            except Exception as exc:
                errors.append(f"line {index}: {exc}")

    rows = [by_date[date] for date in sorted(by_date)]
    if not rows:
        errors.append("empty ohlcv")
    if len(rows) < min_bars:
        errors.append(f"insufficient daily bars: {len(rows)} < {min_bars}")
    if duplicate_count:
        warnings.append(f"deduped duplicate dates: {duplicate_count}")
    if raw_count and len(rows) != raw_count and not duplicate_count:
        warnings.append(f"row count changed from {raw_count} to {len(rows)}")

    if errors:
        raise QualityError(errors, warnings)

    meta = {
        "rows": len(rows),
        "start": rows[0]["date"],
        "end": rows[-1]["date"],
        "duplicates_removed": duplicate_count,
        "warnings": warnings,
    }
    return rows, meta


def write_clean_ohlcv(rows: list[dict[str, Any]], output: str | Path) -> None:
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REQUIRED_OHLCV)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row[field] for field in REQUIRED_OHLCV})


def validate_ohlcv(path: str | Path, output: str | Path | None = None, min_bars: int = 60) -> dict[str, Any]:
    rows, meta = read_and_clean_ohlcv(path, min_bars=min_bars)
    if output:
        write_clean_ohlcv(rows, output)
        meta["output"] = str(output)
    return {"status": "ok", **meta}


def validate_realtime(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    missing = [field for field in REQUIRED_REALTIME if field not in payload or payload[field] in ("", None)]
    if missing:
        raise QualityError([f"missing realtime fields: {', '.join(missing)}"])
    last = normalize_number(payload["last"], "last")
    if last < 0:
        raise QualityError(["negative realtime last"])
    return {"status": "ok", "symbol": payload["symbol"], "timestamp": payload["timestamp"], "last": last}


def classify_empty(reason: str | None, raw_summary: str | None = None) -> dict[str, Any]:
    value = reason if reason in EMPTY_REASONS else "unknown_empty"
    messages = {
        "non_trading_day": "所选日期为非交易日。",
        "no_data_in_range": "区间有效，但没有可用交易记录。",
        "before_listing": "查询区间早于上市日期。",
        "invalid_params": "参数错误，请检查代码、市场和日期。",
        "permission_denied": "接口权限不足或认证不可用。",
        "unknown_empty": "接口返回空结果，原因未能可靠判断。",
    }
    result = {"status": "empty", "empty_reason": value, "message": messages[value]}
    if raw_summary:
        result["raw_summary"] = raw_summary
    return result


def infer_empty_reason(
    start: str | None = None,
    end: str | None = None,
    listing_date: str | None = None,
    provider_reason: str | None = None,
) -> str:
    """Infer a stable empty-result reason without claiming provider failure.

    The inference is deliberately conservative. Permission and invalid-symbol
    errors should come from provider adapters; this helper only uses dates and
    optional listing metadata.
    """
    if provider_reason in EMPTY_REASONS:
        return provider_reason
    try:
        start_date = normalize_date(start) if start else None
        end_date = normalize_date(end) if end else None
    except ValueError:
        return "invalid_params"
    if start_date and end_date and end_date < start_date:
        return "invalid_params"
    if listing_date and end_date:
        try:
            if dt.date.fromisoformat(end_date) < dt.date.fromisoformat(normalize_date(listing_date)):
                return "before_listing"
        except ValueError:
            pass
    if start_date and end_date and start_date == end_date:
        day = dt.date.fromisoformat(start_date)
        if day.weekday() >= 5:
            return "non_trading_day"
    if start_date and end_date:
        return "no_data_in_range"
    return "unknown_empty"


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate normalized market data")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output")
    parser.add_argument("--kind", choices=["ohlcv", "realtime"], default="ohlcv")
    parser.add_argument("--min-bars", type=int, default=60)
    args = parser.parse_args()

    try:
        if args.kind == "ohlcv":
            result = validate_ohlcv(args.input, args.output, min_bars=args.min_bars)
        else:
            result = validate_realtime(args.input)
        print(json.dumps(result, ensure_ascii=False))
    except QualityError as exc:
        print(json.dumps({"status": "error", "errors": exc.errors, "warnings": exc.warnings}, ensure_ascii=False))
        raise SystemExit(2)


if __name__ == "__main__":
    main()
