#!/usr/bin/env python3
"""File-cache helpers for market data artifacts.

The cache is intentionally simple: predictable filenames plus segment metadata.
It is enough for MVP reuse, incremental refresh, and resume without introducing
a database dependency.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


HISTORY_KINDS = {"daily", "weekly", "benchmark"}


def parse_date(value: str | dt.date) -> dt.date:
    if isinstance(value, dt.date):
        return value
    text = str(value).strip().replace("-", "")
    if len(text) != 8 or not text.isdigit():
        raise ValueError(f"date must be YYYY-MM-DD or YYYYMMDD: {value!r}")
    return dt.date(int(text[:4]), int(text[4:6]), int(text[6:8]))


def compact_date(value: str | dt.date) -> str:
    return parse_date(value).strftime("%Y%m%d")


def iso_date(value: str | dt.date) -> str:
    return parse_date(value).isoformat()


@dataclass(frozen=True)
class CacheSegment:
    kind: str
    symbol: str
    start: dt.date
    end: dt.date
    asof: dt.date
    path: Path

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "symbol": self.symbol,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "asof": self.asof.isoformat(),
            "path": str(self.path),
        }


class CacheManager:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.base_dir = self.root / "base"
        self.history_dir = self.root / "history"
        self.realtime_dir = self.root / "realtime"
        self.meta_dir = self.root / "meta"

    def ensure_dirs(self) -> None:
        for directory in (self.base_dir, self.history_dir, self.realtime_dir, self.meta_dir):
            directory.mkdir(parents=True, exist_ok=True)

    def history_filename(
        self,
        kind: str,
        symbol: str,
        start: str | dt.date,
        end: str | dt.date,
        asof: str | dt.date | None = None,
    ) -> str:
        if kind not in HISTORY_KINDS:
            raise ValueError(f"unsupported history kind: {kind}")
        stamp = compact_date(asof or dt.date.today())
        return f"{kind}_{symbol}_{compact_date(start)}_{compact_date(end)}_{stamp}.csv"

    def history_path(
        self,
        kind: str,
        symbol: str,
        start: str | dt.date,
        end: str | dt.date,
        asof: str | dt.date | None = None,
    ) -> Path:
        return self.history_dir / self.history_filename(kind, symbol, start, end, asof=asof)

    def realtime_filename(self, symbol: str, timestamp: dt.datetime | str | None = None) -> str:
        if timestamp is None:
            stamp = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
        elif isinstance(timestamp, dt.datetime):
            stamp = timestamp.strftime("%Y%m%dT%H%M%S")
        else:
            stamp = str(timestamp).replace("-", "").replace(":", "").replace(" ", "T")[:15]
        return f"realtime_{symbol}_{stamp}.json"

    def realtime_path(self, symbol: str, timestamp: dt.datetime | str | None = None) -> Path:
        return self.realtime_dir / self.realtime_filename(symbol, timestamp=timestamp)

    def parse_history_filename(self, path: str | Path) -> CacheSegment | None:
        candidate = Path(path)
        match = re.fullmatch(
            r"(?P<kind>daily|weekly|benchmark)_(?P<symbol>[^_]+)_"
            r"(?P<start>\d{8})_(?P<end>\d{8})_(?P<asof>\d{8})\.csv",
            candidate.name,
        )
        if not match:
            return None
        return CacheSegment(
            kind=match.group("kind"),
            symbol=match.group("symbol"),
            start=parse_date(match.group("start")),
            end=parse_date(match.group("end")),
            asof=parse_date(match.group("asof")),
            path=candidate,
        )

    def find_history_segments(self, kind: str, symbol: str) -> list[CacheSegment]:
        if kind not in HISTORY_KINDS:
            raise ValueError(f"unsupported history kind: {kind}")
        if not self.history_dir.exists():
            return []
        segments: list[CacheSegment] = []
        for path in self.history_dir.glob(f"{kind}_{symbol}_*.csv"):
            parsed = self.parse_history_filename(path)
            if parsed and parsed.kind == kind and parsed.symbol == symbol:
                segments.append(parsed)
        return sorted(segments, key=lambda segment: (segment.start, segment.end, segment.asof))

    def plan_history(self, kind: str, symbol: str, start: str | dt.date, end: str | dt.date) -> dict[str, Any]:
        requested_start = parse_date(start)
        requested_end = parse_date(end)
        if requested_end < requested_start:
            raise ValueError("end date must be >= start date")

        segments = [
            segment for segment in self.find_history_segments(kind, symbol)
            if segment.end >= requested_start and segment.start <= requested_end
        ]
        ranges = [(max(segment.start, requested_start), min(segment.end, requested_end)) for segment in segments]
        merged = merge_ranges(ranges)
        missing = subtract_ranges((requested_start, requested_end), merged)

        if not segments:
            hit_type = "miss"
        elif not missing:
            hit_type = "full"
        else:
            hit_type = "partial"

        return {
            "kind": kind,
            "symbol": symbol,
            "requested": {"start": requested_start.isoformat(), "end": requested_end.isoformat()},
            "hit_type": hit_type,
            "cached_files": [segment.to_dict() for segment in segments],
            "missing_ranges": [{"start": s.isoformat(), "end": e.isoformat()} for s, e in missing],
            "provenance": {
                "cache_files": [str(segment.path) for segment in segments],
                "requires_fetch": bool(missing),
            },
        }

    def write_segment_metadata(self, cache_path: str | Path, metadata: dict[str, Any]) -> Path:
        self.ensure_dirs()
        source = Path(cache_path)
        target = self.meta_dir / f"{source.stem}.json"
        payload = {"cache_file": str(source), **metadata}
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return target


def merge_ranges(ranges: list[tuple[dt.date, dt.date]]) -> list[tuple[dt.date, dt.date]]:
    if not ranges:
        return []
    ordered = sorted(ranges)
    merged: list[tuple[dt.date, dt.date]] = [ordered[0]]
    for start, end in ordered[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end + dt.timedelta(days=1):
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def subtract_ranges(
    requested: tuple[dt.date, dt.date],
    covered: list[tuple[dt.date, dt.date]],
) -> list[tuple[dt.date, dt.date]]:
    start, end = requested
    missing: list[tuple[dt.date, dt.date]] = []
    cursor = start
    for cover_start, cover_end in merge_ranges(covered):
        if cover_end < cursor:
            continue
        if cover_start > end:
            break
        if cover_start > cursor:
            missing.append((cursor, min(cover_start - dt.timedelta(days=1), end)))
        cursor = max(cursor, cover_end + dt.timedelta(days=1))
        if cursor > end:
            break
    if cursor <= end:
        missing.append((cursor, end))
    return missing


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect file cache coverage")
    parser.add_argument("--cache-root", required=True)
    parser.add_argument("--kind", choices=sorted(HISTORY_KINDS), required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    args = parser.parse_args()

    manager = CacheManager(args.cache_root)
    print(json.dumps(manager.plan_history(args.kind, args.symbol, args.start, args.end), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
