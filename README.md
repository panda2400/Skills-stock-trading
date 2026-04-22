# Stock Trading Assistant

> **只读的 A 股 / 美股交易决策辅助 Skill** · **Read-only decision-support skill for A-share & US equities**

一个编排型的 Claude / Codex Skill。它把行情数据源(Futu / Longbridge / Tushare)和确定性的技术分析引擎 `stock-technical-analysis` 串联起来,产出**条件式**的交易决策参考 —— 不会帮你下单、改单或撤单。

An orchestration skill for Claude / Codex that wires together market-data providers (Futu / Longbridge / Tushare) and the deterministic `stock-technical-analysis` engine to produce **conditional** trading decision support. It never places, modifies, or cancels orders.

---

## 中文版

### 功能概览

- **多数据源回退**:Futu(OpenD 可用时优先)→ Longbridge(AI 原生回退)→ Tushare(仅 A 股基本面/资金/板块/宏观研究增强)。
- **本地标准化**:所有行情输出统一落地为标准 OHLCV CSV 与快照 JSON,再进入分析。
- **缓存感知**:基于文件的增量缓存,仅拉取缺失区间,报告中标注缓存出处与数据缺口。
- **数据质量闸门**:在调用技术分析之前做 schema / 去重 / 排序 / 非法 OHLC / 样本量检查,空数据显式分类。
- **只读安全边界**:硬拒所有下单、改单、撤单、解锁类接口;输出语言为条件式(如「若日收站上 44.20 且量能确认,突破条件可观察」)。
- **跨宿主一致**:Codex 与 Claude Code 使用同一套 provider 合约,仅工具访问路径不同。

### 目录结构

```
.
├── SKILL.md                      # Skill 入口与工作流规则
├── agents/
│   └── openai.yaml               # OpenAI / Codex 适配配置
├── scripts/
│   ├── run_analysis.py           # 端到端编排入口
│   ├── normalize_ohlcv.py        # Provider JSON → 标准 OHLCV CSV
│   ├── quality_check.py          # CSV 与实时快照校验
│   ├── cache_manager.py          # 文件缓存与来源标记
│   ├── symbol_map.py             # A 股 / 美股代码归一化
│   └── providers/                # Futu / Longbridge / Tushare 适配器
├── references/                   # 架构、合约、缓存、质量、安全、宿主等规范
└── evals/                        # 合约测试与离线 fixtures
```

### 工作流

```
用户请求
  → symbol_map(代码/市场归一化)
  → provider 健康检查
  → 抓取 provider 原始 JSON
  → normalize_ohlcv(落地为标准 CSV)
  → cache_manager(增量复用)
  → quality_check(阻断脏数据)
  → stock-technical-analysis/analyze.py
  → stock-technical-analysis/render.py
  → 实时触发状态附录(若有)
  → 最终只读报告
```

### 使用前提

- 至少配置一个 Provider:Futu OpenD(本机运行)/ Longbridge SDK / Tushare Token。
- 已安装配套的技术分析 Skill `stock-technical-analysis`(本仓库只负责编排,不包含引擎本身)。
- Python 3.11+。

### 安全边界(硬约束)

- **禁止**调用任何下单 / 改单 / 撤单 / 解锁接口(Futu `place_order.py`、`modify_order.py`、`cancel_order.py`、交易解锁、Longbridge 下单工具等)。
- 输出必须是**条件式决策辅助**,不得出现「现在买入」「卖出这只股票」这类祈使句。
- K 线、快照、财报日期、基准数据一律不得臆造;缺失即标注「数据不足」。

### 交付前自检清单

- Provider 输出已归一化为标准 CSV / JSON。
- 数据质量检查通过,或失败原因被明确汇报。
- 空结果有显式原因分类。
- 缓存出处在报告中可见。
- 技术分析引擎仅基于本地文件被调用。
- 未触达任何下单类工具。
- 最终语言为条件式决策辅助。

---

## English Version

### Overview

- **Multi-provider fallback**: Futu (preferred when OpenD is reachable) → Longbridge (AI-native fallback) → Tushare (A-share research enrichment only: financials, valuation, capital flow, sectors, macro, screening).
- **Local normalization**: every provider output is persisted as standard OHLCV CSV / snapshot JSON before analysis.
- **Cache-aware**: file-based incremental cache — only the missing date range is fetched; cache provenance and gaps are surfaced in the report.
- **Data-quality gate**: schema, dedup, sorting, illegal-OHLC, and sample-size checks run before `stock-technical-analysis`. Empty results are classified, not swallowed as a generic interface error.
- **Read-only safety boundary**: all order placement / modification / cancellation / unlock APIs are hard-denied. Output uses conditional language (e.g. *"if the daily close holds 44.20 with volume confirmation, the breakout setup becomes observable"*).
- **Host-consistent**: the same provider contract is used in Codex and Claude Code; only the tool-access path differs.

### Repository Layout

```
.
├── SKILL.md                      # Skill entry point & workflow rules
├── agents/
│   └── openai.yaml               # OpenAI / Codex adapter config
├── scripts/
│   ├── run_analysis.py           # End-to-end orchestration entry
│   ├── normalize_ohlcv.py        # Provider JSON → standard OHLCV CSV
│   ├── quality_check.py          # CSV & realtime snapshot validation
│   ├── cache_manager.py          # File cache helpers & provenance
│   ├── symbol_map.py             # A-share / US symbol normalization
│   └── providers/                # Futu / Longbridge / Tushare adapters
├── references/                   # Architecture / contracts / cache / quality / safety / hosts
└── evals/                        # Contract tests and offline fixtures
```

### Workflow

```
User request
  → symbol_map (resolve code & market)
  → provider healthcheck
  → fetch provider raw JSON
  → normalize_ohlcv (persist standard CSV)
  → cache_manager (incremental reuse)
  → quality_check (block bad data)
  → stock-technical-analysis/analyze.py
  → stock-technical-analysis/render.py
  → realtime trigger appendix (if available)
  → final read-only report
```

### Prerequisites

- At least one provider configured: local Futu OpenD, Longbridge SDK, or Tushare token.
- Companion skill `stock-technical-analysis` installed (this repo only orchestrates; it does not contain the engine itself).
- Python 3.11+.

### Safety Boundary (Hard Rules)

- **Never** call any order-placement / modification / cancellation / unlock API — including Futu `place_order.py`, `modify_order.py`, `cancel_order.py`, trade-unlock endpoints, and any Longbridge order tools.
- Output must be **conditional decision support**; imperative phrasing such as *"buy now"* or *"sell this stock"* is forbidden.
- Never fabricate bars, snapshots, earnings dates, or benchmark data. Missing data must be reported as "data insufficient".

### Pre-Delivery Checklist

- Provider output was normalized to the standard contracts.
- Data-quality checks passed, or the failure was reported clearly.
- Empty results carry an explicit reason.
- Cache provenance is visible in the report.
- `stock-technical-analysis` was invoked only against local files.
- No trading / order-placement tool was ever called.
- Final language is conditional decision support.

---

## References / 参考文档

- [architecture](references/architecture.md) — responsibilities & data flow / 职责与数据流
- [provider-contract](references/provider-contract.md) — provider methods, symbols, CSV/JSON contracts / Provider 方法与合约
- [data-quality](references/data-quality.md) — validation & empty-result classification / 校验与空结果分类
- [cache-policy](references/cache-policy.md) — file cache layout & incremental update / 缓存布局与增量更新
- [host-adapters](references/host-adapters.md) — Codex & Claude Code execution paths / 宿主执行路径
- [safety](references/safety.md) — read-only safety boundary / 只读安全边界

## License

暂未指定 / Not specified.
