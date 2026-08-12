---
name: strategy-module-composer
description: Map trading-strategy descriptions, creator ideas, articles, or video summaries to the V8 Decision Engine's existing Strategy Modules and compose candidate Templates. Use when Codex needs to decompose strategy logic into Market Context, Direction, Target, Evidence, Risk, Execution, and Management; identify reusable modules, configuration differences, adapters, conflicts, data requirements, or true capability gaps; and avoid duplicate module development before backtesting.
---

# Strategy Module Composer

Use the repository's live registry as the only module source. Produce an architecture proposal, not a profitability claim or deployment approval.

## Load the current catalog

Run from the V8 repository root with the project Python that can import pandas. In an isolated V8 worktree, the standard command is:

```bash
rtk proxy ../../venv/bin/python .agents/skills/strategy-module-composer/scripts/catalog.py --repo .
```

From the primary repository use `venv/bin/python` instead. Use `--stage <stage>` or `--status <status>` to narrow large results. Read `docs/STRATEGY_MODULE_CATALOG.md` only for evidence and explanations; never treat its hand-written counts as newer than the registry output.

## Compose a strategy

1. Preserve every explicit user rule. Mark missing rules as unresolved; do not invent thresholds, timeframes, fill behavior, or risk settings.
2. Split the description into these responsibilities:
   - Market Context: what data is legally available now and the market regime.
   - Direction: long, short, neutral, or permissions.
   - Target: destination and invalidation.
   - Evidence: proof required before entry; keep independent evidence separate.
   - Risk: RR, costs, sizing, leverage, and rejection gates.
   - Execution: standardized entry, stop, target, size, and expiry intent.
   - Management: break-even, partial exit, trailing, time stop, and exit intent.
3. Compare each responsibility with the live Catalog's capability, inputs, outputs, config fields, requirements, availability, profile, conflicts, version, and status.
4. Classify each match as exactly one of:
   - `reuse`: capability and contract already match.
   - `config`: same capability; only supported configuration differs.
   - `adapter`: capability matches but input or output shape needs a bounded conversion.
   - `gap`: no existing Module provides the capability.
5. Prefer `parity-verified` Modules. Do not silently reuse `transitional`, `identified`, or `deprecated` entries as production-ready capabilities.
6. Propose one or more candidate Templates with ordered Module IDs and explicit config differences. Reject duplicate IDs, stage mismatch, unavailable data, future-data access, unmet requirements, or declared conflicts.
7. For every `gap`, name the nearest existing Module and the exact behavioral or contract difference. Recommend a new Module only when configuration or a small adapter cannot cover it.
8. Route accepted changes through specification, dependency-aware tickets, TDD, the frozen `backtest-engine/v1`, immutable artifacts, and review. Do not modify engine fill, cost, position, or metric semantics.

## Output contract

Return these sections:

1. `需求摘要`: strategy objective and explicit rules.
2. `七階段拆解`: a table with stage, source rule, matched Module, classification, confidence, and unresolved detail.
3. `候選 Template`: ordered Module IDs, versions, configs, requirements, and conflicts.
4. `真正缺口`: only `gap` items, each compared with the nearest existing Module.
5. `驗證路徑`: minimum bounded tests, required data, fixed-engine comparison, and artifact gates.

State module counts from the live Catalog. If no rule exists for a stage, label it unresolved instead of inserting a default. Keep performance research separate from the architecture proposal.
