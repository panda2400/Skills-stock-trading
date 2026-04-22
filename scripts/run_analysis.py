#!/usr/bin/env python3
"""Orchestrate provider fetch, cache, quality checks, and technical analysis."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR / "providers"))

from cache_manager import CacheManager
from normalize_ohlcv import normalize_records, write_ohlcv_csv
from quality_check import QualityError, classify_empty, infer_empty_reason, validate_ohlcv, validate_realtime
from symbol_map import analysis_market, benchmark_symbol, display_symbol, normalize_symbol, to_analysis_ticker

import futu_provider
import longbridge_provider


PROVIDERS = {"futu": futu_provider, "longbridge": longbridge_provider}
DENIED_SCRIPT_NAMES = {"place_order.py", "modify_order.py", "cancel_order.py"}


def records_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    for key in ("items", "klines", "candles"):
        if isinstance(payload.get(key), list):
            return payload[key]
    return []


def read_csv_rows(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def merge_csv_files(files: list[Path], output: Path) -> dict[str, Any]:
    by_date: dict[str, dict[str, Any]] = {}
    for path in files:
        for row in read_csv_rows(path):
            if row.get("date"):
                by_date[row["date"]] = row
    rows = [by_date[date] for date in sorted(by_date)]
    write_ohlcv_csv(rows, output)
    return {"rows": len(rows), "files": [str(path) for path in files], "output": str(output)}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def provider_module(name: str):
    if name not in PROVIDERS:
        raise ValueError(f"unsupported provider: {name}")
    return PROVIDERS[name]


def ensure_read_only_paths(stock_ta_dir: Path) -> None:
    for denied in DENIED_SCRIPT_NAMES:
        matches = list(stock_ta_dir.rglob(denied)) if stock_ta_dir.exists() else []
        if matches:
            raise RuntimeError(f"Denied trade script unexpectedly found under analysis engine: {matches[0]}")


def fetch_segment_to_cache(
    provider_name: str,
    symbol: str,
    start: str,
    end: str,
    kind: str,
    cache: CacheManager,
    work_dir: Path,
) -> dict[str, Any]:
    provider = provider_module(provider_name)
    period = "1w" if kind == "weekly" and provider_name == "futu" else "day" if provider_name == "longbridge" else "1d"
    if kind == "benchmark":
        target_symbol = symbol
    else:
        target_symbol = symbol

    payload = provider.get_history_kline(target_symbol, start=start, end=end, period=period)
    records = records_from_payload(payload)
    if not records:
        reason = None
        if isinstance(payload, dict):
            reason = infer_empty_reason(
                start=start,
                end=end,
                listing_date=payload.get("listing_date"),
                provider_reason=payload.get("empty_reason"),
            )
        empty = classify_empty(reason, raw_summary=json.dumps(payload, ensure_ascii=False)[:500])
        return {"status": "empty", **empty}

    rows = normalize_records(records)
    segment_path = cache.history_path(kind, target_symbol, start, end)
    write_ohlcv_csv(rows, segment_path)
    meta = validate_ohlcv(segment_path, min_bars=1)
    cache.write_segment_metadata(segment_path, {
        "provider": provider_name,
        "kind": kind,
        "symbol": target_symbol,
        "start": start,
        "end": end,
        "quality": meta,
    })
    raw_path = work_dir / "raw" / f"{kind}_{target_symbol}_{start}_{end}.json"
    write_json(raw_path, payload)
    return {"status": "fetched", "path": str(segment_path), "raw": str(raw_path), "quality": meta}


def resolve_history(
    provider_name: str,
    symbol: str,
    start: str,
    end: str,
    kind: str,
    cache: CacheManager,
    work_dir: Path,
    provided_csv: Path | None = None,
    min_bars: int = 60,
) -> dict[str, Any]:
    clean_output = work_dir / "normalized" / f"{kind}_{symbol}_{start}_{end}_clean.csv"
    if provided_csv:
        meta = validate_ohlcv(provided_csv, output=clean_output, min_bars=min_bars)
        return {
            "status": "provided_csv",
            "path": str(clean_output),
            "provenance": {"provided": str(provided_csv), "cache_files": [], "new_fetches": []},
            "quality": meta,
        }

    cache.ensure_dirs()
    plan = cache.plan_history(kind, symbol, start, end)
    fetches: list[dict[str, Any]] = []
    if plan["missing_ranges"]:
        for segment in plan["missing_ranges"]:
            fetches.append(fetch_segment_to_cache(
                provider_name,
                symbol,
                segment["start"],
                segment["end"],
                kind,
                cache,
                work_dir,
            ))

    empty_fetches = [item for item in fetches if item.get("status") == "empty"]
    if empty_fetches and not plan["cached_files"]:
        return {"status": "empty", "empty": empty_fetches[0], "plan": plan}

    cache_files = [Path(item["path"]) for item in plan["cached_files"]]
    cache_files.extend(Path(item["path"]) for item in fetches if item.get("status") == "fetched")
    if not cache_files:
        return {"status": "empty", "empty": classify_empty("unknown_empty"), "plan": plan}

    merge_meta = merge_csv_files(cache_files, clean_output)
    quality = validate_ohlcv(clean_output, output=clean_output, min_bars=min_bars)
    return {
        "status": "ok",
        "path": str(clean_output),
        "plan": plan,
        "merge": merge_meta,
        "quality": quality,
        "provenance": {
            "cache_files": [item["path"] for item in plan["cached_files"]],
            "new_fetches": [item for item in fetches if item.get("status") == "fetched"],
            "empty_fetches": empty_fetches,
        },
    }


def resolve_snapshot(provider_name: str, symbol: str, cache: CacheManager, work_dir: Path, provided_json: Path | None = None) -> dict[str, Any]:
    if provided_json:
        meta = validate_realtime(provided_json)
        return {"status": "provided_json", "path": str(provided_json), "quality": meta}

    provider = provider_module(provider_name)
    try:
        states = provider.get_snapshot([symbol])
    except Exception as exc:
        return {"status": "degraded", "message": str(exc)}
    if not states:
        return {"status": "empty", **classify_empty("unknown_empty")}

    realtime_path = cache.realtime_path(symbol)
    write_json(realtime_path, states[0])
    try:
        meta = validate_realtime(realtime_path)
    except QualityError as exc:
        return {"status": "degraded", "path": str(realtime_path), "errors": exc.errors}
    return {"status": "ok", "path": str(realtime_path), "quality": meta}


def run_command(command: list[str], cwd: Path | None = None) -> None:
    lowered = " ".join(command).lower()
    if any(name in lowered for name in DENIED_SCRIPT_NAMES):
        raise RuntimeError(f"Denied trade command: {' '.join(command)}")
    completed = subprocess.run(command, cwd=str(cwd) if cwd else None, text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(command)}\n{completed.stderr or completed.stdout}")


def render_realtime_block(snapshot_result: dict[str, Any]) -> str:
    if snapshot_result.get("status") not in {"ok", "provided_json"}:
        reason = snapshot_result.get("message") or snapshot_result.get("empty_reason") or "实时快照不可用"
        return f"\n\n## 实时快照状态\n\n实时快照未纳入本次判断：{reason}。\n"
    payload = json.loads(Path(snapshot_result["path"]).read_text(encoding="utf-8"))
    last = payload.get("last")
    prev_close = payload.get("prev_close")
    move = ""
    try:
        if last is not None and prev_close:
            pct = (float(last) / float(prev_close) - 1) * 100
            move = f"，较昨收 {pct:+.2f}%"
    except (TypeError, ValueError, ZeroDivisionError):
        move = ""
    return (
        "\n\n## 实时快照状态\n\n"
        f"- 来源：{payload.get('provider')}，时间：{payload.get('timestamp')}\n"
        f"- 最新价：{last}{move}\n"
        "- 该快照只用于判断条件是否接近触发，不单独构成买卖建议。\n"
    )


def append_runner_footer(report_path: Path, snapshot_result: dict[str, Any], provenance: dict[str, Any]) -> None:
    text = report_path.read_text(encoding="utf-8")
    footer = render_realtime_block(snapshot_result)
    footer += "\n## 数据来源与缓存\n\n"
    cache_files = provenance.get("daily", {}).get("provenance", {}).get("cache_files", [])
    new_fetches = provenance.get("daily", {}).get("provenance", {}).get("new_fetches", [])
    footer += f"- 日线缓存命中：{len(cache_files)} 个文件。\n"
    footer += f"- 日线新拉取：{len(new_fetches)} 个区间。\n"
    benchmark_status = provenance.get("benchmark", {}).get("status", "missing")
    footer += f"- 基准数据状态：{benchmark_status}。\n"
    footer += "\n技术面分析不是投资建议，需结合财报、公告、流动性和个人风险承受能力。\n"
    report_path.write_text(text.rstrip() + "\n" + footer, encoding="utf-8")


def run_analysis(args: argparse.Namespace) -> dict[str, Any]:
    symbol = normalize_symbol(args.symbol)
    end = args.end or dt.date.today().isoformat()
    start = args.start or (dt.date.fromisoformat(end) - dt.timedelta(days=420)).isoformat()
    work_dir = Path(args.out_dir) / symbol
    work_dir.mkdir(parents=True, exist_ok=True)

    stock_ta_dir = Path(args.stock_ta_dir)
    ensure_read_only_paths(stock_ta_dir)
    cache = CacheManager(args.cache_root or (Path(__file__).resolve().parents[1] / "cache"))

    daily = resolve_history(
        args.provider,
        symbol,
        start,
        end,
        "daily",
        cache,
        work_dir,
        provided_csv=Path(args.daily_csv) if args.daily_csv else None,
        min_bars=60,
    )
    if daily.get("status") == "empty":
        return {"status": "empty", "symbol": symbol, "daily": daily}

    bench_symbol = benchmark_symbol(symbol)
    benchmark: dict[str, Any] = {"status": "missing"}
    try:
        benchmark = resolve_history(
            args.provider,
            bench_symbol,
            start,
            end,
            "benchmark",
            cache,
            work_dir,
            provided_csv=Path(args.benchmark_csv) if args.benchmark_csv else None,
            min_bars=20,
        )
    except Exception as exc:
        benchmark = {"status": "degraded", "message": str(exc), "rs_mode": "qualitative"}

    snapshot = {"status": "skipped"} if args.skip_snapshot else resolve_snapshot(
        args.provider,
        symbol,
        cache,
        work_dir,
        provided_json=Path(args.snapshot_json) if args.snapshot_json else None,
    )

    state_path = work_dir / f"{symbol}_state.json"
    report_path = work_dir / f"{symbol}_technical_report.md"
    analyze_py = stock_ta_dir / "scripts" / "analyze.py"
    render_py = stock_ta_dir / "scripts" / "render.py"
    if not analyze_py.exists() or not render_py.exists():
        raise FileNotFoundError(f"stock-technical-analysis engine not found under {stock_ta_dir}")

    analyze_cmd = [
        sys.executable,
        str(analyze_py),
        "--ticker",
        to_analysis_ticker(symbol),
        "--market",
        analysis_market(symbol),
        "--daily",
        daily["path"],
        "--out",
        str(state_path),
        "--risk-profile",
        args.risk_profile,
        "--account-size",
        str(args.account_size),
    ]
    if benchmark.get("status") in {"ok", "provided_csv"} and benchmark.get("path"):
        analyze_cmd.extend(["--benchmark", benchmark["path"]])
    run_command(analyze_cmd)

    run_command([sys.executable, str(render_py), "--state", str(state_path), "--template", args.template, "--out", str(report_path)])
    provenance = {"daily": daily, "benchmark": benchmark, "snapshot": snapshot}
    append_runner_footer(report_path, snapshot, provenance)

    manifest = {
        "status": "ok",
        "symbol": symbol,
        "display_symbol": display_symbol(symbol),
        "provider": args.provider,
        "state": str(state_path),
        "report": str(report_path),
        "provenance": provenance,
    }
    write_json(work_dir / "run_manifest.json", manifest)
    return manifest


def main() -> None:
    default_ta = Path(__file__).resolve().parents[2] / "stock-technical-analysis"
    parser = argparse.ArgumentParser(description="Run read-only stock trading assistant analysis")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--provider", choices=sorted(PROVIDERS), default="futu")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--out-dir", default="/tmp/stock-trading-assistant")
    parser.add_argument("--cache-root")
    parser.add_argument("--stock-ta-dir", default=str(default_ta))
    parser.add_argument("--daily-csv")
    parser.add_argument("--benchmark-csv")
    parser.add_argument("--snapshot-json")
    parser.add_argument("--skip-snapshot", action="store_true")
    parser.add_argument("--risk-profile", choices=["conservative", "balanced", "aggressive"], default="balanced")
    parser.add_argument("--account-size", type=float, default=100000)
    parser.add_argument("--template", default="zh-S1")
    args = parser.parse_args()

    try:
        print(json.dumps(run_analysis(args), ensure_ascii=False, indent=2))
    except QualityError as exc:
        print(json.dumps({"status": "quality_error", "errors": exc.errors, "warnings": exc.warnings}, ensure_ascii=False, indent=2))
        raise SystemExit(2)


if __name__ == "__main__":
    main()
