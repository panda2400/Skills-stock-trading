#!/usr/bin/env python3
"""Top-level Skill contract and language-safety tests."""

from __future__ import annotations

import csv
import datetime as dt
import os
import re
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVESTMENT_ROOT = ROOT.parent


def parse_frontmatter(text: str) -> dict[str, str]:
    self = {}
    if not text.startswith("---\n"):
        return self
    _, block, _ = text.split("---", 2)
    for line in block.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            self[key.strip()] = value.strip().strip('"')
    return self


def write_ohlcv(path: Path, rows: int = 90, start_price: float = 100.0) -> None:
    start = dt.date(2026, 1, 1)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["date", "open", "high", "low", "close", "volume"])
        writer.writeheader()
        for i in range(rows):
            close = start_price + i * 0.45
            writer.writerow({
                "date": (start + dt.timedelta(days=i)).isoformat(),
                "open": f"{close - 0.2:.2f}",
                "high": f"{close + 1.1:.2f}",
                "low": f"{close - 1.0:.2f}",
                "close": f"{close:.2f}",
                "volume": str(1000000 + i * 5000),
            })


class SkillContractTest(unittest.TestCase):
    def test_frontmatter_only_name_and_description(self) -> None:
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        frontmatter = parse_frontmatter(text)
        self.assertEqual(set(frontmatter), {"name", "description"})
        self.assertEqual(frontmatter["name"], "stock-trading-assistant")

    def test_openai_metadata(self) -> None:
        text = (ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertIn("Stock Trading Assistant", text)
        self.assertIn("$stock-trading-assistant", text)

    def test_references_linked_from_skill_exist(self) -> None:
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        links = re.findall(r"\((references/[^)]+)\)", text)
        self.assertGreaterEqual(len(links), 6)
        for link in links:
            self.assertTrue((ROOT / link).exists(), link)

    def test_safety_hard_denies_trade_scripts(self) -> None:
        safety = (ROOT / "references" / "safety.md").read_text(encoding="utf-8")
        runner = (ROOT / "scripts" / "run_analysis.py").read_text(encoding="utf-8")
        for name in ("place_order.py", "modify_order.py", "cancel_order.py"):
            self.assertIn(name, safety)
            self.assertIn(name, runner)

    def test_fixture_to_rendered_report_has_no_unconditional_trade_language(self) -> None:
        ta_dir = INVESTMENT_ROOT / "stock-technical-analysis"
        if not (ta_dir / "scripts" / "analyze.py").exists():
            self.skipTest("stock-technical-analysis engine not available")

        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            daily = tmpdir / "daily.csv"
            bench = tmpdir / "benchmark.csv"
            state = tmpdir / "state.json"
            report = tmpdir / "report.md"
            write_ohlcv(daily, rows=90, start_price=100)
            write_ohlcv(bench, rows=90, start_price=400)

            analyze = subprocess.run(
                [
                    sys.executable,
                    str(ta_dir / "scripts" / "analyze.py"),
                    "--ticker",
                    "AAPL",
                    "--market",
                    "US",
                    "--daily",
                    str(daily),
                    "--benchmark",
                    str(bench),
                    "--out",
                    str(state),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(analyze.returncode, 0, analyze.stderr or analyze.stdout)
            render = subprocess.run(
                [
                    sys.executable,
                    str(ta_dir / "scripts" / "render.py"),
                    "--state",
                    str(state),
                    "--template",
                    "zh-S1",
                    "--out",
                    str(report),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(render.returncode, 0, render.stderr or render.stdout)
            text = report.read_text(encoding="utf-8")
            blocked = ("应该买入", "应该卖出", "无条件买入", "无条件卖出", "立刻买入", "立刻卖出")
            for phrase in blocked:
                self.assertNotIn(phrase, text)
            self.assertIn("技术面决策辅助", text)

    def test_runner_with_provided_csv_uses_read_only_pipeline(self) -> None:
        ta_dir = INVESTMENT_ROOT / "stock-technical-analysis"
        if not (ta_dir / "scripts" / "analyze.py").exists():
            self.skipTest("stock-technical-analysis engine not available")

        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            daily = tmpdir / "daily.csv"
            bench = tmpdir / "benchmark.csv"
            write_ohlcv(daily, rows=90, start_price=100)
            write_ohlcv(bench, rows=90, start_price=400)
            run = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "run_analysis.py"),
                    "--symbol",
                    "AAPL.US",
                    "--provider",
                    "futu",
                    "--daily-csv",
                    str(daily),
                    "--benchmark-csv",
                    str(bench),
                    "--skip-snapshot",
                    "--out-dir",
                    str(tmpdir / "out"),
                    "--cache-root",
                    str(tmpdir / "cache"),
                    "--stock-ta-dir",
                    str(ta_dir),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(run.returncode, 0, run.stderr or run.stdout)
            self.assertIn('"status": "ok"', run.stdout)
            report = tmpdir / "out" / "AAPL.US" / "AAPL.US_technical_report.md"
            self.assertTrue(report.exists())
            text = report.read_text(encoding="utf-8")
            self.assertIn("数据来源与缓存", text)
            self.assertIn("实时快照未纳入本次判断", text)

    def test_release_zip_exclusions_when_present(self) -> None:
        release_zip = os.environ.get("RELEASE_ZIP")
        if not release_zip:
            self.skipTest("RELEASE_ZIP not set")
        with zipfile.ZipFile(release_zip) as archive:
            names = archive.namelist()
        forbidden_parts = ("INSTALL.md", "signal_log.jsonl", "__pycache__", "/cache/", "/raw/", "/logs/", ".env")
        for name in names:
            self.assertFalse(any(part in name for part in forbidden_parts), name)
        self.assertIn("stock-trading-assistant/SKILL.md", names)
        self.assertIn("stock-trading-assistant/agents/openai.yaml", names)
        self.assertIn("stock-trading-assistant/evals/fixtures/futu_a_kline.json", names)
        self.assertNotIn("stock-trading-assistant/evals/skill_contract_test.py", names)


if __name__ == "__main__":
    unittest.main()
