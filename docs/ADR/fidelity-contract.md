# ADR-009: Minimal backtest/live fidelity contract

Status: Accepted

Decision:

- 回撤限價單只可使用首次碰到 entry 之後的 1m 路徑；無法判定的同分鐘事件採保守結果。
- 正式 fidelity 報告必須用持倉中 MTM equity 計算 MDD，並固定資料 SHA、Git revision、設定與 baseline identity。
- Live 每次執行必須以交易所實際 fill 與倉位為準；任何已成交數量在成功保存狀態前必須有等量保護，否則安全失敗。
- Flat convergence 只處理可由本系統 client tag 證明 ownership 的倉位與訂單；不碰人工或其他策略部位。
- `research` 可使用明確標示的 fallback；`fidelity` 缺歷史 funding、mark price 或完整資料稽核時必須停止，不得靜默降級。

Consequence:

策略績效可能因正確性修正下降；正式 candidate 必須與 rollback `b7cfc20` 在相同 snapshot、期間、成本與槓桿下比較。實盤可用性仍須通過 testnet/shadow，不因單元測試完成即宣稱 production-ready。
