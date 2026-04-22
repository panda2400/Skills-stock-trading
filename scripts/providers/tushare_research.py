#!/usr/bin/env python3
"""A-share research enrichment adapter for Tushare.

This provider is intentionally not used for technical signal generation. It is
only a read-only enrichment path for finance, valuation, capital flow, sector,
news, macro, or screening tasks.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from typing import Any


RESEARCH_SCOPES = {"finance", "valuation", "capital_flow", "sector", "news", "macro", "screening"}


def healthcheck() -> dict[str, Any]:
    return {
        "provider": "tushare",
        "python_package_found": importlib.util.find_spec("tushare") is not None,
        "token_configured": bool(os.environ.get("TUSHARE_TOKEN")),
        "read_only": True,
        "technical_signal_source": False,
        "supported_scopes": sorted(RESEARCH_SCOPES),
    }


def should_use(scope: str | None) -> bool:
    return bool(scope and scope in RESEARCH_SCOPES)


def require_research_scope(scope: str) -> None:
    if scope not in RESEARCH_SCOPES:
        raise ValueError(f"unsupported Tushare research scope: {scope}")


def unavailable_result(scope: str, reason: str | None = None) -> dict[str, Any]:
    require_research_scope(scope)
    status = healthcheck()
    message = reason
    if message is None:
        if not status["token_configured"]:
            message = "TUSHARE_TOKEN is not configured; research enrichment is skipped."
        elif not status["python_package_found"]:
            message = "tushare Python package is not installed; research enrichment is skipped."
        else:
            message = "Tushare enrichment was not requested by the runner."
    return {"status": "degraded", "provider": "tushare", "scope": scope, "message": message, "healthcheck": status}


def main() -> None:
    parser = argparse.ArgumentParser(description="Tushare read-only research adapter")
    parser.add_argument("--healthcheck", action="store_true")
    parser.add_argument("--scope", choices=sorted(RESEARCH_SCOPES))
    args = parser.parse_args()

    if args.healthcheck or not args.scope:
        print(json.dumps(healthcheck(), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(unavailable_result(args.scope), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
