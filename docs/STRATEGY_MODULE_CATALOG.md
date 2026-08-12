# V8 Strategy Module Catalog

> Initial inventory: 2026-08-09

本文件是規格階段的可讀盤點。Module manifest／registry 是唯一資料來源；目前 live source 為 `nfe_v2_plugin_registry().catalog()`，本文件由其產生或驗證。

## Count

| Status | Count | Meaning |
|---|---:|---|
| `parity-verified` reusable strategy modules | 8 | V2 第一版的市場資料、方向、價格目標、兩層證據、風險、下單與管理模組已通過 exact parity。 |
| `implemented` reusable strategy modules | 0 | 目前沒有只完成實作但尚未通過 parity 的 V2 Module。 |
| `identified` V2 modules | 0 | V2 第一版已識別模組均已抽取；仍待組成 Template 與 parity 驗證。 |
| `transitional` compatibility providers | 7 | 七階段相容／telemetry providers，不算完成 Module。 |

Plugin／Template schema、Pipeline scaffold、comparison identity、frozen baseline 與 parity safeguards 是平台能力，不列入策略模組數。

## Identified V2 Modules

| Module ID | Stage | Status | Capability | Main output |
|---|---|---|---|---|
| `v2.closed_bar_context` | Market Context | `parity-verified` | 建立合法可用的 HTF／LTF closed-bar view。 | Market context |
| `v2.htf_structure_direction` | Direction | `parity-verified` | 依 HTF swing／BOS 判斷方向。 | Direction result |
| `v2.swing_liquidity_target` | Target | `parity-verified` | 識別 swing、liquidity target 與 invalidation。 | Target result |
| `v2.htf_ob_retrace` | Evidence | `parity-verified` | 判斷 HTF Order Block retrace。 | Evidence result |
| `v2.ltf_structure_confirmation` | Evidence | `parity-verified` | 判斷 LTF confirmed structure break。 | Evidence result |
| `v2.rr_cost_risk_gate` | Risk | `parity-verified` | 檢查 RR、cost、sizing 與 leverage feasibility。 | Risk result |
| `v2.retrace_limit_execution` | Execution | `parity-verified` | 產生 retrace limit、SL、TP 與 size intent。 | Execution intent |
| `v2.atr_structural_management` | Management | `parity-verified` | 產生 TP1、BE、time／liq 政策與 ATR trailing intent。 | Management intent |

Module ID 在追蹤 legacy implementation、確認責任邊界與 tickets 核准後固定。

目前 live evidence：`v2.closed_bar_context` 的 public Pipeline 測試證明 HTF release 與 LTF prefix 不讀取 future rows；`v2.htf_structure_direction` 已覆蓋多空權限、confirmed long／short structure 與 prefix invariance，且不呼叫完整 legacy scan。

完成 evidence：`v2.swing_liquidity_target` 已覆蓋多方與空方價格目標、失效價及共用時間切斷入口，不呼叫完整 legacy scan。

完成 evidence：`v2.htf_ob_retrace` 已覆蓋多方與空方有效區域回踩條件並輸出可追蹤 contribution；不執行低週期確認、風險或下單。

完成 evidence：`v2.ltf_structure_confirmation` 已覆蓋多空結構突破與 entry OB 輸出，並由 Registry 強制 HTF retrace 必須先於 LTF confirmation。

完成 evidence：`v2.rr_cost_risk_gate` 已覆蓋多空 fee-adjusted minimum RR、dynamic／static stop padding、execution ratio、net-profit RR、risk-based／fixed-margin sizing、volume／leverage cap 及 short-quality 拒絕原因；不建立成交或修改 position。

完成 evidence：`v2.retrace_limit_execution` 已將多空 Risk decision 轉成標準 retrace-limit intent，包含 created-at／expiry、effective／limit entry、SL、TP1／remote TP2、size、balance、RR、risk 與 V2 entry mode；不模擬 fill、不修改 position。

完成 evidence：`v2.atr_structural_management` 已覆蓋多空 TP1／TP2、BE trigger、time-stop 上限、liquidation guard 與 dynamic／static ATR structural stop；僅輸出 policy／move-stop intent，不解析同棒 fill 順序或直接修改 active position。

組合 evidence：`v2_modular` 已依七階段順序組成上述 8 個 Modules，並保留完整 config snapshot、accepted／rejected contribution 與 reason funnel。Bounded long／short、prefix 與 management 與 legacy 一致，Backtest adapter 不呼叫完整 legacy scan。正式 artifact `20260811T003004Z_schema_v2_17376de` 證明 legacy／modular 的 89 筆 trades 與 12,920 筆 realized equity SHA exact；AUD-016 以 C0／H0／M0／L1 Accept，因此 8 個 Modules 升級為 `parity-verified`。

跨策略組合 evidence：STR-015 以 `other.fixed_long_direction` test double 建立第二個 Template，只替換 Direction 並沿用其他 7 個 V2 Modules。Pipeline contributions 與標準 V2 除 Direction identity 外一致，兩者經同一 BacktestStrategy adapter 產生相同 retrace order；Registry 同時證明外部 Module 不得以重複 ID 覆蓋已驗證 V2 Module。Test double 不列入 Catalog 模組數，也不宣稱策略績效。

## Required Manifest Fields

| Field | Purpose |
|---|---|
| `module_id` / `version` | Stable identity。 |
| `stage` / `capability` | 單一責任與 Pipeline 位置。 |
| `inputs` / `outputs` | Public contract。 |
| `config_schema` | 參數、預設與 fail-closed validation。 |
| `data_requirements` | OHLCV、timeframe、Volume Profile 等需求。 |
| `availability_rule` | Closed-bar、timezone 與可用時間。 |
| `reason_codes` | Accept、reject、unavailable 原因。 |
| `compatibility` | Dependencies、valid combinations 與 conflicts。 |
| `status` | identified、transitional、implemented、parity-verified、deprecated。 |
| `tests` / `evidence` | Unit、prefix、parity 與 source evidence。 |
| `templates` | 使用此 Module 的 Templates。 |

## Skill Matching Output

Strategy Module Composer Skill 收到自然語言策略時輸出：

1. 七階段責任拆解。
2. 對應 Module ID 與匹配信心。
3. 直接重用、config difference、adapter 或 true gap 分類。
4. Candidate Template 與 data requirements。
5. Conflicts、duplicate information 與 temporal risks。
6. 未定義規則及需向使用者確認的問題。
7. 新 Module 與最接近現有 Module 的具體差異。

Skill 不判定獲利能力；所有組合仍須通過 frozen Backtest Engine 與正式驗收。
