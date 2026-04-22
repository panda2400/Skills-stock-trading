#!/usr/bin/env python3
"""Normalize provider kline JSON into the standard OHLCV CSV contract."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
from pathlib import Path
from typing import Any


REQUIRED = ("date", "open", "high", "low", "close", "volume")


def _records_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        raise ValueError("provider payload must be a JSON object or list")
    data = payload.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    if isinstance(payload.get("items"), list):
        return payload["items"]
    if isinstance(payload.get("klines"), list):
        return payload["klines"]
    return []


def normalize_date(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("missing date")
    text = text.replace("/", "-")
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    candidate = text[:10]
    try:
        return dt.date.fromisoformat(candidate).isoformat()
    except ValueError as exc:
        raise ValueError(f"invalid date: {text}") from exc


def _number(value: Any, field: str) -> float:
    if value is None or value == "":
        raise ValueError(f"missing {field}")
    return float(str(value).replace(",", ""))


def normalize_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in records:
        date_value = (
            row.get("date")
            or row.get("time")
            or row.get("time_key")
            or row.get("timestamp")
            or row.get("datetime")
        )
        normalized.append({
            "date": normalize_date(date_value),
            "open": _number(row.get("open"), "open"),
            "high": _number(row.get("high"), "high"),
            "low": _number(row.get("low"), "low"),
            "close": _number(row.get("close"), "close"),
            "volume": _number(row.get("volume"), "volume"),
        })

    # Last row wins on duplicate date, then stable ascending sort.
    by_date = {row["date"]: row for row in normalized}
    return [by_date[d] for d in sorted(by_date)]


def write_ohlcv_csv(rows: list[dict[str, Any]], output: str | Path) -> None:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REQUIRED)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row[key] for key in REQUIRED})


def normalize_json_file(input_path: str | Path, output_path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(input_path).read_text(encoding="utf-8"))
    rows = normalize_records(_records_from_payload(payload))
    write_ohlcv_csv(rows, output_path)
    return {"rows": len(rows), "output": str(output_path)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize provider kline JSON to OHLCV CSV")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = normalize_json_file(args.input, args.output)
    print(json.dumps({"status": "ok", **result}, ensure_ascii=False))


if __name__ == "__main__":
    main()
