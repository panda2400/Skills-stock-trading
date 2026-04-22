#!/usr/bin/env python3
"""Cache naming, coverage, and resume behavior tests."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from cache_manager import CacheManager


CSV = "date,open,high,low,close,volume\n2026-01-01,1,2,1,2,100\n"


class CachePolicyTest(unittest.TestCase):
    def test_history_naming(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = CacheManager(tmp)
            name = manager.history_filename("daily", "600519.SH", "2026-01-01", "2026-01-31", asof="2026-04-21")
            self.assertEqual(name, "daily_600519.SH_20260101_20260131_20260421.csv")
            realtime = manager.realtime_filename("600519.SH", "2026-04-21T10:32:15")
            self.assertEqual(realtime, "realtime_600519.SH_20260421T103215.json")

    def test_full_hit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = CacheManager(tmp)
            manager.ensure_dirs()
            path = manager.history_path("daily", "AAPL.US", "2026-01-01", "2026-01-31", asof="2026-04-21")
            path.write_text(CSV, encoding="utf-8")
            plan = manager.plan_history("daily", "AAPL.US", "2026-01-05", "2026-01-20")
            self.assertEqual(plan["hit_type"], "full")
            self.assertFalse(plan["missing_ranges"])

    def test_partial_hit_and_incremental_gap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = CacheManager(tmp)
            manager.ensure_dirs()
            manager.history_path("daily", "AAPL.US", "2026-01-01", "2026-01-10", asof="2026-04-21").write_text(CSV, encoding="utf-8")
            manager.history_path("daily", "AAPL.US", "2026-01-15", "2026-01-20", asof="2026-04-21").write_text(CSV, encoding="utf-8")
            plan = manager.plan_history("daily", "AAPL.US", "2026-01-01", "2026-01-20")
            self.assertEqual(plan["hit_type"], "partial")
            self.assertEqual(plan["missing_ranges"], [{"start": "2026-01-11", "end": "2026-01-14"}])

    def test_failed_segment_without_csv_is_retried(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = CacheManager(tmp)
            manager.ensure_dirs()
            manager.write_segment_metadata(manager.history_path("daily", "AAPL.US", "2026-01-01", "2026-01-31"), {"status": "failed"})
            plan = manager.plan_history("daily", "AAPL.US", "2026-01-01", "2026-01-31")
            self.assertEqual(plan["hit_type"], "miss")
            self.assertEqual(plan["missing_ranges"], [{"start": "2026-01-01", "end": "2026-01-31"}])


if __name__ == "__main__":
    unittest.main()
