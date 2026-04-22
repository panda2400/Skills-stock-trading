#!/usr/bin/env python3
"""Read-only adapter around the existing Futu Skill quote scripts."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from symbol_map import benchmark_symbol, market_of, normalize_symbol, to_futu


DEFAULT_FUTU_SKILL_DIR = Path("/Users/panda/Skills/skills/futuapi")
QUOTE_DIR = Path("scripts/quote")
DENIED_TRADE_SCRIPTS = {"place_order.py", "modify_order.py", "cancel_order.py"}


class ProviderError(RuntimeError):
    def __init__(self, message: str, reason: str = "unknown_empty", raw_summary: str | None = None):
        super().__init__(message)
        self.reason = reason
        self.raw_summary = raw_summary or message


def _skill_dir(skill_dir: str | Path | None = None) -> Path:
    return Path(skill_dir or os.environ.get("FUTU_SKILL_DIR") or DEFAULT_FUTU_SKILL_DIR)


def quote_script(name: str, skill_dir: str | Path | None = None) -> Path:
    if name in DENIED_TRADE_SCRIPTS or "trade" in Path(name).parts:
        raise ProviderError(f"trade script is denied: {name}", reason="invalid_params")
    path = _skill_dir(skill_dir) / QUOTE_DIR / name
    if not path.exists():
        raise ProviderError(f"Futu quote script not found: {path}", reason="invalid_params")
    return path


def healthcheck(
    skill_dir: str | Path | None = None,
    opend_host: str = "127.0.0.1",
    opend_port: int = 11111,
    timeout: float = 0.5,
) -> dict[str, Any]:
    root = _skill_dir(skill_dir)
    scripts_ok = all((root / QUOTE_DIR / script).exists() for script in ("get_kline.py", "get_snapshot.py"))
    opend_reachable = False
    opend_error = None
    try:
        with socket.create_connection((opend_host, opend_port), timeout=timeout):
            opend_reachable = True
    except OSError as exc:
        opend_error = str(exc)
    return {
        "provider": "futu",
        "skill_dir": str(root),
        "scripts_ok": scripts_ok,
        "opend_reachable": opend_reachable,
        "opend_error": opend_error,
        "read_only": True,
        "denied_trade_scripts": sorted(DENIED_TRADE_SCRIPTS),
    }


def resolve_symbol(symbol: str) -> dict[str, str]:
    canonical = normalize_symbol(symbol)
    return {"symbol": canonical, "provider_symbol": to_futu(canonical), "market": market_of(canonical)}


def _classify_error(text: str) -> str:
    lower = text.lower()
    if any(word in text for word in ("权限", "认证", "额度", "登录")) or "permission" in lower:
        return "permission_denied"
    if any(word in lower for word in ("invalid", "bad parameter", "参数")):
        return "invalid_params"
    if "opend" in lower or "connection" in lower or "连接" in text:
        return "permission_denied"
    return "unknown_empty"


def _parse_json_output(output: str) -> dict[str, Any]:
    try:
        return json.loads(output or "{}")
    except json.JSONDecodeError:
        pass
    for line in output.splitlines():
        candidate = line.strip()
        if candidate.startswith("{") or candidate.startswith("["):
            try:
                payload = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                return payload
            return {"data": payload}
    raise json.JSONDecodeError("No JSON object found in provider output", output, 0)


def _run_json(script_name: str, args: list[str], skill_dir: str | Path | None = None) -> dict[str, Any]:
    script = quote_script(script_name, skill_dir=skill_dir)
    completed = subprocess.run(
        [sys.executable, str(script), *args, "--json"],
        text=True,
        capture_output=True,
        check=False,
    )
    output = (completed.stdout or "").strip()
    if completed.returncode != 0:
        raw = (completed.stderr or completed.stdout or "").strip()
        raise ProviderError(f"Futu command failed: {raw}", reason=_classify_error(raw), raw_summary=raw[:500])
    try:
        payload = _parse_json_output(output)
    except json.JSONDecodeError as exc:
        raise ProviderError(f"Futu returned non-JSON output: {output[:300]}", raw_summary=output[:500]) from exc
    if isinstance(payload, dict) and payload.get("error"):
        message = str(payload["error"])
        raise ProviderError(message, reason=_classify_error(message), raw_summary=message[:500])
    return payload


def get_history_kline(
    symbol: str,
    start: str,
    end: str,
    period: str = "1d",
    rehab: str = "forward",
    skill_dir: str | Path | None = None,
) -> dict[str, Any]:
    resolved = resolve_symbol(symbol)
    payload = _run_json(
        "get_kline.py",
        [
            resolved["provider_symbol"],
            "--ktype",
            period,
            "--start",
            start,
            "--end",
            end,
            "--num",
            "1000",
            "--rehab",
            rehab,
        ],
        skill_dir=skill_dir,
    )
    payload.setdefault("symbol", resolved["symbol"])
    payload.setdefault("provider_symbol", resolved["provider_symbol"])
    payload.setdefault("provider", "futu")
    if not payload.get("data"):
        payload["empty_reason"] = payload.get("empty_reason") or "unknown_empty"
    return payload


def get_snapshot(symbols: list[str], skill_dir: str | Path | None = None) -> list[dict[str, Any]]:
    resolved = [resolve_symbol(symbol) for symbol in symbols]
    payload = _run_json("get_snapshot.py", [item["provider_symbol"] for item in resolved], skill_dir=skill_dir)
    rows = payload.get("data") if isinstance(payload, dict) else []
    if not rows:
        return []

    by_provider_code = {item["provider_symbol"]: item for item in resolved}
    states: list[dict[str, Any]] = []
    now = dt.datetime.now().isoformat(timespec="seconds")
    for row in rows:
        provider_code = str(row.get("code") or "")
        resolved_item = by_provider_code.get(provider_code) or resolve_symbol(provider_code)
        canonical = resolved_item["symbol"] if isinstance(resolved_item, dict) else normalize_symbol(provider_code)
        states.append({
            "symbol": canonical,
            "market": market_of(canonical),
            "provider": "futu",
            "timestamp": row.get("update_time") or now,
            "last": row.get("last") if row.get("last") is not None else row.get("last_price"),
            "open": row.get("open"),
            "high": row.get("high"),
            "low": row.get("low"),
            "volume": row.get("volume"),
            "turnover": row.get("turnover"),
            "bid": row.get("bid"),
            "ask": row.get("ask"),
            "prev_close": row.get("prev_close"),
        })
    return states


def get_benchmark(symbol: str, start: str, end: str, skill_dir: str | Path | None = None) -> dict[str, Any]:
    return get_history_kline(benchmark_symbol(symbol), start=start, end=end, period="1d", skill_dir=skill_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description="Futu read-only provider adapter")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("healthcheck")

    resolve_p = sub.add_parser("resolve")
    resolve_p.add_argument("symbol")

    kline_p = sub.add_parser("kline")
    kline_p.add_argument("symbol")
    kline_p.add_argument("--start", required=True)
    kline_p.add_argument("--end", required=True)
    kline_p.add_argument("--period", default="1d")
    kline_p.add_argument("--rehab", default="forward")

    snap_p = sub.add_parser("snapshot")
    snap_p.add_argument("symbols", nargs="+")

    args = parser.parse_args()
    try:
        if args.command == "healthcheck":
            result = healthcheck()
        elif args.command == "resolve":
            result = resolve_symbol(args.symbol)
        elif args.command == "kline":
            result = get_history_kline(args.symbol, args.start, args.end, period=args.period, rehab=args.rehab)
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
