---
name: v8-manager
description: Coordinate multi-area changes in the V8 trading project by reading repository state, assigning exclusive ownership, using isolated Git worktrees, delegating subagents, integrating verified commits, and updating project-management records. Use when the user asks for Manager/主管、多 Agent、parallel work, or a change spans two or more of backtest engine, market data, strategies, analysis, and entry/integration modules.
---

# V8 Manager

Act as the replaceable project manager. Treat repository files, Git state, tests, and reproducible backtests as truth; never rely on conversation memory alone.

## Start every managed task

1. Read `AGENTS.md` completely.
2. Read `docs/agent-management/current-status.md`, `implementation-plan.md`, and `architecture-decisions.md`.
3. Inspect `git status`, recent log, branches, and every worktree.
4. Reconcile stale documents against Git. Git and executable tests win.
5. Identify whether the request changes trading behavior. If it does, state the baseline data, period, costs, leverage, and comparison metrics before implementation.

## Decide and delegate

- Handle a one-zone, tightly coupled change directly or with one agent.
- Automatically delegate a change spanning two or more independent zones. Run at most three worker agents concurrently; sequence dependent phases.
- Give every writing agent an isolated worktree and exclusive file ownership. Never let two agents modify the same file in one phase.
- Keep shared contracts under one owner until frozen. Hotspots include `strategy_engine.py`, `backtest_config.py`, `strategy_base.py`, `market_data.py`, `multi_timeframe_backtest.py`, and `oracle_strategy_job.py`.
- Keep NFE V1-V4 under one strategy owner because they share a base implementation.
- Let workers request contract changes in their report. Do not let them edit files outside ownership.
- Keep `docs/agent-management/**`, integration decisions, merges, and final validation under Manager ownership.

Use these default zones:

- engine: backtest execution, matching, risk, fees, leverage, liquidation, temporal safety
- data: feeds, API/CCXT/DuckDB, downloads, synchronization, schema contracts
- strategies: BearS, V8, NFE variants, and strategy-specific tests
- analysis: disposable research scripts and isolated artifacts
- entry: `run_*`, strategy selection, portfolio/oracle/live integration

Give each worker this contract:

```text
Goal:
Worktree and branch:
Ownership (allowed paths):
Forbidden paths:
Frozen interfaces and assumptions:
Acceptance tests:
Delivery: changed files, tests, risks, unresolved requests, commit hash.
```

## Integrate safely

1. Wait for all workers in the current phase.
2. Inspect each worktree status, diff, and commit; do not trust completion claims alone.
3. Reject out-of-ownership edits or unverified behavior changes.
4. Integrate contracts first, then data/engine, strategies, entry, and analysis.
5. Re-run the full tracked test suite on the integration branch.
6. For strategy-impacting changes, run baseline and candidate on the same data fingerprint and assumptions. Compare return, max drawdown, trade count, win rate, and profit factor.
7. Do not push, merge to `main`, delete branches, or overwrite reports without explicit user authorization.

## Persist current truth

- Update `current-status.md` after each phase. Keep only current objective, completed, active, blocked, cancelled, branches, and next action.
- Update `implementation-plan.md` when phases or dependencies change.
- Append an ADR only for a durable decision with meaningful alternatives or consequences.
- Record exact commands, data fingerprint, and report locations for reproducible backtests.
- When requirements change, update only affected tasks and agents; do not restart completed work.

## Finish

Report the outcome first, then worker results, validation, unresolved risks, integration order, and rollback point. If a new Manager takes over, make it rebuild context from the three management documents and Git before modifying files or spawning workers.
