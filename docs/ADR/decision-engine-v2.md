# ADR-011: Modular V2 template over a frozen backtest engine

Status: Accepted

## Context

最初的 compatibility-first Pipeline 已建立 Plugin／Template schema、七階段 execution scaffold、artifact identity 與 legacy parity 護欄。但目前只有 Execution provider 呼叫完整 legacy V2 scan，其餘 stage 主要提供 telemetry，Management 仍在 Pipeline 外。

這能保護行為，卻尚未達成使用者要的能力：將 V2 真實策略邏輯拆成可供其他策略替換、交叉組合及公平回測的模組。

## Decision

V8 以 Market Context、Direction、Target、Evidence、Risk、Execution、Management 為策略責任 Pipeline。legacy V2 的實際邏輯必須抽成 stage-specific reusable Modules，再由它們組成第一個完整 `v2_modular` Template。

現有 `nfe_v2_compatible` 保留為 compatibility／instrumentation scaffold，不視為模組化完成成果。legacy `NFEV2Strategy` 保持唯讀 baseline。

所有 Template 只輸出標準化 analysis、trade 與 management intent。現有 Backtest Engine 繼續唯一負責資料時序、fill ordering、費用、滑價、funding、倉位、槓桿、清算、equity、MDD、PF、ledger 與 artifact base semantics；本輪凍結這些行為。

Module manifest／registry 是能力與狀態的唯一資料來源，並產生或驗證 Strategy Module Catalog。Repository 內另建 Codex Skill，將外部策略描述拆解後優先匹配、設定及組合既有 Modules，只有確認能力缺口後才建議新增 Module。

## Consequences

- 可以在不複製整套 V2 下重用或替換 Direction、Target、Evidence、Risk、Execution 及 Management 能力。
- 策略比較維持同一 Backtest Engine，避免用不同成交或 metrics semantics 製造假差異。
- 必須逐一抽取並證明 closed-bar、prefix、long／short、order intent、ATR management 與 exact legacy parity。
- Compatibility scaffold、schema 與 identity 成果繼續提供 regression value，不需推倒重做。
- Catalog 與 Skill 增加治理工作，但以同一 registry 為事實來源，避免重複模組與文件漂移。
- 新策略描述先產生可審查的組合提案；仍須經規格、tickets、TDD、回測與 audit，不能直接部署。
