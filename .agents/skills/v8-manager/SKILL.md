---
name: v8-manager
description: Run a stateless Manager for multi-area changes in the V8 trading project by rebuilding context from repository state, assigning exclusive ownership, using isolated Git worktrees, delegating subagents, integrating verified commits, and persisting handoff state. Use when the user asks for Manager/主管、多 Agent、parallel work, or a change spans two or more of backtest engine, market data, strategies, analysis, and entry/integration modules.
---

# V8 Stateless Manager

Act as a replaceable Manager. Never depend on chat memory for project truth.

## Rebuild context first

At the start of every managed turn, read and inspect in this order:

1. `PROJECT_STATE.md`
2. `TASK_BOARD.md`
3. `AGENTS.md` completely
4. every Markdown file directly under `docs/ADR/`
5. the latest relevant commits, current branch status, branch list, and every worktree status

Do not modify files, create branches, or spawn workers before completing this intake. Reconcile stale documents against Git and executable tests; Git and tests win. Update stale state before delegation.

Identify whether the request changes trading behavior. If it does, record the baseline data, period, costs, leverage, and comparison metrics before implementation.

## Decide and delegate

- Handle a one-zone, tightly coupled change directly or with one worker.
- Automatically delegate a change spanning two or more independent zones. Run at most three workers concurrently; sequence dependent phases.
- Give every writing worker an isolated worktree and exclusive file ownership. Never let two workers modify the same file in one phase.
- Keep shared contracts under one owner until frozen. Hotspots include `strategy_engine.py`, `backtest_config.py`, `strategy_base.py`, `market_data.py`, `multi_timeframe_backtest.py`, and `oracle_strategy_job.py`.
- Keep NFE V1-V4 under one strategy owner.
- Let workers request contract changes in their report instead of editing outside ownership.
- Keep `PROJECT_STATE.md`, `TASK_BOARD.md`, `docs/ADR/**`, integration decisions, merges, and final validation under Manager ownership.

Use these default zones:

- engine: execution, matching, risk, fees, leverage, liquidation, temporal safety
- data: feeds, API/CCXT/DuckDB, downloads, synchronization, schema contracts
- strategies: BearS, V8, NFE variants, and strategy-specific tests
- analysis: disposable research scripts and isolated artifacts
- entry: `run_*`, strategy selection, portfolio/oracle/live integration

Give each worker this contract:

```text
Goal:
Task ID:
Worktree and branch:
Ownership (allowed paths):
Forbidden paths:
Frozen interfaces and assumptions:
Acceptance tests:
Delivery: changed files, tests, risks, unresolved requests, commit hash.
```

## Integrate safely

1. Mark assigned tasks in progress on `TASK_BOARD.md` before dispatch.
2. Wait for every worker in the current phase.
3. Inspect each worktree status, diff, tests, and commit; do not trust completion claims alone.
4. Reject out-of-ownership edits or unverified behavior changes.
5. Integrate contracts first, then data/engine, strategies, entry, and analysis.
6. Re-run the full tracked test suite on the integration branch.
7. For strategy-impacting changes, run baseline and candidate on the same data fingerprint and assumptions. Compare return, max drawdown, trade count, win rate, and profit factor.
8. Do not push, merge to `main`, delete branches, or overwrite reports without explicit user authorization.

## Persist the handoff

- Keep `PROJECT_STATE.md` short and current: objective, phase, verified baseline, active branches/worktrees, conflicts, and next checkpoint.
- Keep `TASK_BOARD.md` actionable: task ID, status, owner, worktree, dependencies, ownership, acceptance, and result commit.
- Add or change an ADR only for a durable decision with meaningful alternatives or consequences.
- Update state and task board after each phase and before ending the turn.
- When requirements change, update only affected tasks; preserve valid completed work.

Finish with worker results, validation, unresolved risks, integration order, and rollback point. A new Manager must repeat the full intake instead of inheriting assumptions from the previous thread.
