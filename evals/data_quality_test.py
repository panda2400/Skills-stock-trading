#!/usr/bin/env python3
"""Data quality rule tests."""

from __future__ import annotations

import csv
import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from quality_check import QualityError, classify_empty, infer_empty_reason, validate_ohlcv


def write_rows(path: Path, rows: list[dict[str, object]], fields: list[str] | None = None) -> None:
    fields = fields or ["date", "open", "high", "low", "close", "volume"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def valid_rows(count: int = 61) -> list[dict[str, object]]:
    start = dt.date(2026, 1, 1)
    rows = []
    for i in range(count):
        close = 100 + i * 0.5
        rows.append({
            "date": (start + dt.timedelta(days=i)).isoformat(),
            "open": f"{close - 0.2:.2f}",
            "high": f"{close + 1.0:.2f}",
            "low": f"{close - 1.0:.2f}",
            "close": f"{close:.2f}",
            "volume": f"{1000000 + i}",
        })
    return rows


class DataQualityTest(unittest.TestCase):
    def test_valid_rows_are_sorted_deduped_and_typed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.csv"
            output = Path(tmp) / "clean.csv"
            rows = valid_rows()
            rows = [rows[2], rows[0], rows[1], *rows[3:], rows[1]]
            write_rows(path, rows)
            result = validate_ohlcv(path, output=output, min_bars=60)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["duplicates_removed"], 1)
            self.assertEqual(result["start"], "2026-01-01")

    def test_missing_columns_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.csv"
            write_rows(path, [{"date": "2026-01-01", "open": 1}], fields=["date", "open"])
            with self.assertRaises(QualityError) as caught:
                validate_ohlcv(path)
            self.assertIn("missing columns", caught.exception.errors[0])

    def test_invalid_ohlc_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.csv"
            rows = valid_rows()
            rows[10]["high"] = "90"
            rows[10]["low"] = "101"
            write_rows(path, rows)
            with self.assertRaises(QualityError) as caught:
                validate_ohlcv(path)
            self.assertTrue(any("high < low" in err for err in caught.exception.errors))

    def test_insufficient_sample_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "short.csv"
            write_rows(path, valid_rows(20))
            with self.assertRaises(QualityError) as caught:
                validate_ohlcv(path)
            self.assertTrue(any("insufficient daily bars" in err for err in caught.exception.errors))

    def test_empty_result_classification(self) -> None:
        self.assertEqual(classify_empty("non_trading_day")["empty_reason"], "non_trading_day")
        self.assertEqual(classify_empty("before_listing")["empty_reason"], "before_listing")
        self.assertEqual(classify_empty("bad_value")["empty_reason"], "unknown_empty")
        self.assertEqual(infer_empty_reason("2026-04-18", "2026-04-18"), "non_trading_day")
        self.assertEqual(infer_empty_reason("2020-01-01", "2020-01-02", listing_date="2020-02-01"), "before_listing")
        self.assertEqual(infer_empty_reason("2026-01-02", "2026-01-31"), "no_data_in_range")


if __name__ == "__main__":
    unittest.main()
