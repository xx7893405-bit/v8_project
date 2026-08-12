# V8 Decision Engine 與可抽換策略模型

Issue: [#58](https://github.com/xx7893405-bit/v8_project/issues/58)

## 1. 需求與最終目標

本設計把現行 NFE V2 的真實策略邏輯拆成可重用、可抽換、可設定及可比較的策略模組，再以這些模組組成第一個完整模板 `v2_modular`。

V2 是第一個被組合與驗證的 Template，不是 Decision Engine 本身。未來策略可以只替換某一個模組，或沿用 V2 的個別模組，而不必複製整套 V2 或重寫回測流程。

```text
Strategy Modules
       ↓ compose
Strategy Template（第一個是 V2）
       ↓ standardized analysis / trade / management intent
Frozen Backtest Engine
       ↓
Immutable artifacts and fair comparison
```

完成後應能表達例如：

- V2 Direction + MA Evidence。
- V2 Direction + Volume Profile Target。
- Other Direction + V2 Risk。
- Other Evidence + V2 Execution Intent。

每個組合都使用同一個 Backtest Engine，因此結果差異只能來自 Template、Module 與 resolved config，而不是成交或績效計算規則改變。

## 2. 目前成果的正確定位

現有 `nfe_v2_compatible`、Plugin／Template schema、七階段 Pipeline、comparison identity、frozen baseline 與 parity safeguards 全部保留。

但目前只有 Execution provider 呼叫完整 legacy V2 scan，其他 provider 主要輸出 ownership／compatibility telemetry，實際持倉管理仍在 Pipeline 外。因此：

- 它是抽取期間的 compatibility／instrumentation scaffold。
- 它提供 regression 與 parity 護欄。
- 它不是 V2 已完成模組化的證據。

本規格的完成條件是抽出真實 V2 邏輯，並由這些模組組成 V2 Template；不能只增加 provider 名稱、分數或 telemetry。

## 3. Frozen Backtest Engine 邊界

Engine contract identity：`backtest-engine/v1`。

本輪不改變 Backtest Engine 的行為與計算語義：

- 歷史資料、timeframe 與 closed-bar／intrabar 時序。
- limit、stop、fill 的處理順序。
- maker／taker fee、slippage、funding。
- position sizing、leverage 與 liquidation。
- equity、realized-only MDD、PF、win rate 與其他 metrics。
- ledger 與既有基礎 artifact contract。

Pipeline 的 Execution／Management 是策略模組，不是 Backtest Engine：

- Execution Module 只輸出標準化 entry、stop、take-profit、size intent。
- Management Module 只輸出標準化保本、移動停損、減碼或出場 intent。
- Backtest Engine 依既有規則模擬 intent 是否及如何成交。

若抽取時發現缺少通用接縫，只能加入最薄的 adapter 或標準化輸入欄位，且必須先記錄、測試及審查；不得改寫成交、成本、部位生命週期或 metrics semantics。

## 4. Pipeline 與 V2 第一版模組

```text
Market Context → Direction → Target → Evidence → Risk → Execution → Management
```

七個 stage 是責任分類，不代表每個 stage 只能有一個 Module。Evidence 等 stage 可由 Template 明確組合多個互補模組。

| Stage | V2 Module | 單一責任 |
|---|---|---|
| Market Context | `v2.closed_bar_context` | 建立當下合法可用的 HTF／LTF closed-bar 市場視圖。 |
| Direction | `v2.htf_structure_direction` | 依 confirmed HTF swing／BOS 判斷方向。 |
| Target | `v2.swing_liquidity_target` | 識別 swing、流動性目標與 invalidation。 |
| Evidence | `v2.htf_ob_retrace` | 判斷價格是否回踩有效 HTF Order Block。 |
| Evidence | `v2.ltf_structure_confirmation` | 判斷 LTF confirmed close break 是否確認。 |
| Risk | `v2.rr_cost_risk_gate` | 檢查最低 RR、fee drag、sizing 與 leverage feasibility。 |
| Execution | `v2.retrace_limit_execution` | 產生 retrace limit entry、SL、TP1、remote TP2 與 size intent。 |
| Management | `v2.atr_structural_management` | 產生 TP1、BE、time／liq 與 ATR structural trailing intent。 |

這些 Module ID 在追蹤 legacy V2 實際資料流、確認責任邊界及 ticket 核准後固定；若實證顯示邊界不正確，先修訂規格，不為了維持表格而扭曲程式。

## 5. Module Contract

每個 Module 必須具有：

- stable `module_id`、version、stage 與 status。
- 可 JSON 序列化且 fail-closed 驗證的 config。
- 明確 input／output contract 與資料需求。
- 有時區的 `signal_time`／`available_at` 與 closed-bar 規則。
- reason codes、facts、profile 與 bounded diagnostics。
- 相依、相容、衝突與使用中的 Template identity。

Module 只能讀取 signal time 已可得的 immutable market context、上游 result 與 resolved run config。未知 Module、重複 ID、stage mismatch、非法 config、缺資料、循環依賴或未來時間一律 fail closed。

Direction／Target 預設各選一個 provider；Evidence 可使用顯式 `all`、`any` 或 `weighted` policy。Policy 與 Module config 必須實際傳入 evaluation，不得只被 schema 驗證後忽略。

## 6. Template Contract

Template 是 Module 與設定的具名組合，至少包含：

- template ID／version。
- 每一 stage 的 ordered Module list。
- enabled state、resolved Module config。
- combine／score policy。
- market、timeframe 與 data requirements。
- intent 與 frozen Backtest Engine assumptions。

Runner 保存 resolved config、config hash、Module versions、Git revision、data identity 與 engine contract identity。

第一個最終模板為 `v2_modular`。它必須由已抽取 Module 組成，且不能再把完整 legacy scan 隱藏在單一 provider。`nfe_v2_compatible` 保留為過渡及 parity scaffold；legacy `NFEV2Strategy` 保留為唯讀 baseline。

## 7. Strategy Module Catalog

Repository 維護一份可計數、可追溯的 Module Catalog。Module manifest／registry 是機器可讀的唯一資料來源；Markdown 清單與 Codex Skill 索引由它產生或驗證，禁止各自手動維護多份事實。

每個 Catalog entry 至少包含：

- Module ID、version、stage、capability。
- inputs、outputs、config schema、data requirements。
- availability rule、reason codes。
- dependencies、compatibility、conflicts。
- status：`identified`、`transitional`、`implemented`、`parity-verified`、`deprecated`。
- tests、parity evidence、source evidence 與使用中的 Templates。

數量必須按 status 分開。Pipeline stage label、compatibility provider 與平台 contract 不得誤算成已完成的可重用策略模組。

初始盤點見 [STRATEGY_MODULE_CATALOG.md](STRATEGY_MODULE_CATALOG.md)。

## 8. Strategy Module Composer Skill

Repository 內建立版本化的 Codex Skill；完成後可安裝至個人 Codex Skills。Skill 讀取同一份 Catalog，不複製策略程式、不維護第二個 registry，也不執行另一套回測。

收到其他創作者的策略描述、文章、影片摘要或自然語言邏輯時，Skill 必須：

1. 拆解成七個 Pipeline stage 的責任。
2. 查 Catalog 並優先匹配既有 Module。
3. 區分直接重用、只需改 config、需要 adapter 與真正缺少新能力。
4. 輸出候選 Template、資料需求、相依、衝突及匹配信心。
5. 標示描述未定義的規則，不自行補造交易邏輯。
6. 只有 Catalog 無合適能力時才建議新增 Module，並列出與最接近既有 Module 的差異。
7. 將新 Template／Module 送回 spec、tickets、TDD 與 frozen-engine backtest 流程，不宣稱策略有效。

Skill 必須以代表性描述 forward-test，至少證明它不會把相同能力因命名差異重複建立。

AI-003 已實作於 `.agents/skills/strategy-module-composer/`。Skill 以 live registry 匯出腳本取得 Catalog，輸出七階段拆解、`reuse`／`config`／`adapter`／`gap`、候選 Template、資料／時序需求、衝突、信心與 unresolved 規則。EMA200 slope＋PDL sweep＋session VWAP reclaim 的獨立 forward-test 正確保留 entry 與剩餘部位管理為 unresolved，且未把 V2 BOS／OB／retrace-limit／ATR management 誤判為可直接重用。

## 9. Frozen Baseline 與 Exact Parity

- 市場：Binance USDT-M `BTC/USDT:USDT`。
- 資料 snapshot：`ea28b7ca3c90c46b`。
- Data SHA-256：`5b8e0da5a65338b5ca14ca6ee919331f82db4df4148edde44b4e046f433a5965`。
- 期間：2021-01-01 至 2026-07-18 13:51 UTC。
- 設定：1H／15m、10,000 USD、risk-based 5%、max 20x、maker 0.02%、taker 0.05%、既有 slippage／funding／execution model。
- Exact-fill legacy baseline：89 trades、return +210.0220%、realized-only MDD -36.5982%、win 40.4494%、PF 1.8393、final 31,002.20。
- 89-entry time／side digest：`4104f109962bb0ce2a6898c86c215f65fe0f6a8678a814b96b29ac56f27ab863`。
- Summary SHA：`3322dfc9c41dd4bb6c4d70e75e2e8bbd91bf748b4a9155fda7197101580dda5f`。
- Trades SHA：`89f3473ef609975d5c6751d00cade9fb97d6e66648db1d097883be822fa21b6c`。
- 2026-07-18 bar-open baseline 已棄用為現行 parity gate，但其 fixture 保留供歷史追溯；它早於 exact retrace-touch commit `a51783e`。
- 正式比較效能門檻為每年不超過 180 秒；完整期間依實際年數線性換算硬上限。

`v2_modular` 必須重現 exact entry-time／side identity、exit／ledger 與 headline metrics。任何差異都停止 publication 並回到模組抽取診斷。MTM MDD 可另列，但不得混用 realized-only baseline 口徑。

## 10. Artifact 與比較

每個 Template 使用獨立 equity curve 與 immutable run ID。Comparison artifact 必須包含：

- resolved config、Module ID／version 與 contributions。
- Git revision、data／cost／execution／engine contract identity。
- MDD convention、summary／trades／equity 實檔與驗證後 SHA。
- ledger identity、reason-code funnel 與 bounded diagnostics。
- entry-time／side exact overlap、保留、排除與新增交易。
- return、final balance、MDD、trades、win rate、PF、average R／payoff、year／side／development／OOS 與 concentration。
- 完整 40 位 Git revision、經 containment 驗證的 run ID、實測 runtime／seconds-per-year／180 秒預算，以及與同一 Git revision 綁定的完整測試指令及通過數。

缺少檔案、hash 不符、baseline identity、snapshot、schema、ledger 或 no-overwrite 任一失敗時 fail closed。Artifact hash 必須由 publisher 驗證實際檔案，不接受 caller 自行宣告存在。

Frozen source 的 `summary_sha256` 與 `trades_sha256` 以實際發布 bytes 計算；發布 materialization 只移除 fixture 的單一結尾 newline，再對剩餘 bytes 做 SHA-256。不得做 JSON 重排、空白正規化或移除多個換行。Repository fixture 保留可讀用的結尾 newline，因此直接對工作樹 fixture bytes 計算會得到不同 digest；正式驗證以 materialized published bytes 為準。

## 11. 實作與驗收順序

1. 固定 Backtest Engine contract 與 regression boundary。
2. 完成 Module contract、manifest／Catalog schema、strict time 與 artifact trust。
3. 逐一以 TDD 抽取 Market Context、Direction、Target、Evidence、Risk。
4. 抽取 Execution／Management intent，不改 engine semantics。
5. 由抽取後 Module 組成 `v2_modular`。
6. 唯讀 preflight Critical／High 歸零。
7. 執行 frozen exact parity 與最終唯讀 audit。
8. 以最小第二來源 Module／test double 證明跨策略替換與重用。
9. 建立並 forward-test Strategy Module Composer Skill。
10. 另立 tickets 研究 V2＋MA、V2＋POC／VAH／VAL 等 opt-in Templates。

公開 seam 採一個 red→green tracer bullet 實作。正式全期間回測只由 backtest role 執行；reviewer 保持唯讀。

STR-015 architecture proof 已完成：`nfe_v2_plugin_registry(extra_plugins)` 可在拒絕重複 Module ID 的前提下注入第二來源 Module；另一個 Template 只替換 Direction、重用其餘 7 個 V2 Modules，並由同一 `V2ModularDecisionTemplate` adapter 產生與標準 V2 相同的 BacktestStrategy order。此 proof 使用 bounded test double，只證明組合與固定回測接縫，不代表第二策略具備績效。

## 12. 驗收防偏移問題

每個主要階段完成後都要回答：

1. 是否抽出真實策略邏輯，而不只是增加包裝或 telemetry？
2. Module 是否能在不複製整套 V2 下被其他 Template 使用或替換？
3. Backtest Engine 的成交、成本、部位及 metrics semantics 是否固定？
4. Modular V2 是否仍可與 legacy V2 精確比較？
5. Catalog 是否正確反映模組數，Skill 是否優先重用而非重複建立？
6. 是否只建立目前驗收需要的最小抽象？

任一答案為否，先修訂規格並取得確認，再調整 tickets 或實作。

## 13. 非目標與回滾

本輪不移除 legacy V2、不更改 live／paper／exchange flow、不做參數最佳化或 ML 訓練、不下載資料、不覆寫 reports，也不觸碰既有 dirty worktrees。

MA／Volume Profile 等只在 modular V2 parity 後另案實作；Skill 的組合建議不是績效保證或部署授權。

Rollback 基準為 `8ef15536bcc83d6befbd74d4ee3228236a9c9743`；所有本輪變更位於 `codex/decision-engine-v2`。
