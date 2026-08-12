# ADR-012: Exact-fill baseline replaces the historical bar-open parity gate

Status: Accepted

## Context

2026-07-18 frozen fixture 將 retrace entry 記為 15m bar open。現行 Decision Engine branch 已包含 2026-07-23 commit `a51783e`，會用 1m 路徑記錄首次 retrace touch 並從 entry 後管理部位。舊 fixture 因此不能代表 frozen `backtest-engine/v1` 的現行成交行為。

## Decision

現行 parity gate 改用 exact-fill legacy baseline：89 trades、return 210.0220%、realized-only MDD -36.5982%、win 40.4494%、PF 1.8393、final 31,002.20。舊 bar-open fixture 保留供歷史追溯，但不再阻擋現行 parity。Backtest Engine、策略參數、資料、成本、槓桿與 metrics semantics 均不修改。

正式比較效能門檻為每年不超過 180 秒，完整期間依年數線性換算。

Frozen source identity 以正式發布 bytes 為準。從 repository fixture materialize 時只移除單一結尾 newline，然後直接計算 SHA-256；不重排 JSON、不正規化其他空白，也不移除更多換行。這個 byte-level 規則是 baseline source SHA 的唯一口徑。

## Consequences

- modular V2 必須 exact-match 現行 legacy 的實際分鐘 entry、exit、完整 ledger、realized equity 與 headline metrics。
- 不得把舊 bar-open 與 exact-fill 結果混為同一 baseline。
- 舊 fixture 不刪除、不覆寫；新 fixture 與 SHA 獨立版本化。
- 正式 parity artifact 必須記錄完整 Git revision、受 containment 保護的 run ID、按期間換算的 runtime evidence，以及綁定同一 revision 的 full-test evidence；任一缺失即停止發布。
