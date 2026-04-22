#!/usr/bin/env python3
"""Provider contract tests using offline fixtures."""

from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "providers"))

from normalize_ohlcv import normalize_json_file
from quality_check import validate_realtime
from symbol_map import normalize_symbol, to_futu, to_longbridge
import futu_provider
import longbridge_provider


class ProviderContractTest(unittest.TestCase):
    def normalize_fixture(self, fixture: str) -> list[dict[str, str]]:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out.csv"
            result = normalize_json_file(ROOT / "evals" / "fixtures" / fixture, output)
            self.assertEqual(result["rows"], 2)
            with output.open("r", encoding="utf-8", newline="") as handle:
                return list(csv.DictReader(handle))

    def test_symbol_formats(self) -> None:
        self.assertEqual(normalize_symbol("SH.600519"), "600519.SH")
        self.assertEqual(normalize_symbol("US.AAPL"), "AAPL.US")
        self.assertEqual(to_futu("600519.SH"), "SH.600519")
        self.assertEqual(to_futu("AAPL.US"), "US.AAPL")
        self.assertEqual(to_longbridge("000001.SZ"), "000001.SZ")

    def test_futu_a_fixture_to_standard_ohlcv(self) -> None:
        rows = self.normalize_fixture("futu_a_kline.json")
        self.assertEqual(rows[0]["date"], "2026-01-02")
        self.assertEqual(set(rows[0]), {"date", "open", "high", "low", "close", "volume"})

    def test_futu_us_fixture_to_standard_ohlcv(self) -> None:
        rows = self.normalize_fixture("futu_us_kline.json")
        self.assertEqual(rows[-1]["close"], "214.6")

    def test_longbridge_a_fixture_to_standard_ohlcv(self) -> None:
        rows = self.normalize_fixture("longbridge_a_kline.json")
        self.assertEqual(rows[0]["date"], "2026-01-02")

    def test_longbridge_us_fixture_to_standard_ohlcv(self) -> None:
        rows = self.normalize_fixture("longbridge_us_kline.json")
        self.assertEqual(rows[0]["volume"], "58000000.0")

    def test_realtime_fixture_contract(self) -> None:
        result = validate_realtime(ROOT / "evals" / "fixtures" / "futu_snapshot.json")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["symbol"], "600519.SH")

    def test_futu_adapter_tolerates_stdout_logs(self) -> None:
        mixed = "2026 log line\n{\"data\": [{\"date\": \"2026-01-02\"}]}\nmore logs"
        payload = futu_provider._parse_json_output(mixed)
        self.assertEqual(payload["data"][0]["date"], "2026-01-02")

    def test_longbridge_a_share_time_and_volume_are_normalized(self) -> None:
        rows = longbridge_provider._normalize_kline_records(
            [{"time": "2026-04-20 16:00:00", "volume": "998567", "open": "34.00"}],
            "A",
        )
        self.assertEqual(rows[0]["date"], "2026-04-21")
        self.assertEqual(rows[0]["volume"], 99856700)

    def test_longbridge_us_volume_is_not_lot_scaled(self) -> None:
        rows = longbridge_provider._normalize_kline_records(
            [{"time": "2026-04-21 04:00:00", "volume": "13470944"}],
            "US",
        )
        self.assertEqual(rows[0]["date"], "2026-04-21")
        self.assertEqual(rows[0]["volume"], 13470944)


if __name__ == "__main__":
    unittest.main()
