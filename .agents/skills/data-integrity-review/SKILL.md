---
name: data-integrity-review
description: >
  僅在「已存在的市場 Dataset 需要首次認證、已認證 Dataset 的實際資料內容發生新增／刪除／修改／修補、或有合理證據懷疑資料異常」時使用。
  Dataset 已認證且內容未變時不要使用。修改策略、參數、Entry／Exit、SL／TP、Indicator、最佳化、Walk-forward、Strategy Screening 或重跑回測時不要使用。
  若本地缺少 Symbol、Market Type、Timeframe 或所需日期範圍不足，也不要使用；應停止回測並要求 Data Acquisition／Dataset Build。
---

# Data Integrity Review

本 Skill 只回答一個問題：**這份已存在的 Dataset 是否可信、能否被認證。**

## 快速判斷

只有以下 3 種情況需要繼續讀本 Skill：

1. 新 Dataset 已存在，但尚未認證。
2. 已認證 Dataset 的實際資料內容被新增、刪除、修改、覆蓋或修補。
3. 有合理證據懷疑 Dataset 存在 Missing、Duplicate、Timestamp、OHLCV、未收盤 K、時區或市場類型等資料問題。

其他情況立即停止讀取本 Skill。

### 明確不觸發

以下情況不得因事件本身觸發本 Skill：

- Dataset 已認證且內容未變。
- 新增或修改策略、Entry／Exit、SL／TP、Indicator、Filter、Position Sizing 或其他策略參數。
- Optimization、Walk-forward、Monte Carlo、Strategy Screening、Strategy Ranking 或大量重跑。
- 本地缺少所需 Symbol、Market Type、Timeframe。
- Dataset 日期範圍不足。
- 策略改用另一個 Timeframe。
- 修改 Fee、Slippage、Funding、Liquidation 或其他成交成本模型。

若缺少資料：**停止回測並回報缺少的 Symbol／Market Type／Timeframe／Date Range，要求 Data Acquisition／Dataset Build。**

不得因缺少 Timeframe 而在回測期間從其他週期臨時 Resample。

---

# 以下內容只有確定觸發後才需要執行

## 執行模式

### 1. 初始驗證

條件：

```text
Dataset exists
AND
Certification does not exist
```

對該 Dataset 執行完整資料完整性驗證；通過後建立 Certification、Manifest 與 Fingerprint。

### 2. 增量驗證

條件：

```text
Dataset already certified
AND
historical data unchanged
AND
only new rows appended
```

只驗證：

- 舊資料尾端。
- 新舊資料接縫。
- 新增資料區段。

不得無理由重新掃描整份已認證歷史資料。

### 3. 重新驗證

適用於：

- 歷史資料被修改、刪除、覆蓋或修補。
- Fingerprint 與認證紀錄不一致。
- 有合理證據懷疑資料異常。
- 無法確認舊 Certification 是否仍有效。

若能可靠界定受影響範圍，只驗證該範圍；無法界定時才完整重新驗證。

## 驗證項目

### Timestamp

檢查：

- Timestamp 單調遞增。
- Duplicate Timestamp。
- Missing Candle／Unexpected Interval。
- Timestamp Alignment。
- Timezone 一致性。
- 適用市場的 Session／DST 問題。

### OHLCV

至少確認：

```text
High >= Open
High >= Close
Low <= Open
Low <= Close
High >= Low
Volume >= 0
```

並檢查 NaN、Null、Infinite、Zero／Negative Price、Negative Volume 與明顯異常值。

### 未收盤 K 線

尚未完成的 K 線不得被認證為正式歷史資料。

### Market Identity

至少確認：

```text
Exchange
Symbol
Base Asset
Quote Asset
Market Type
Contract Type
Timeframe
Timezone
```

必須明確區分 Spot、Futures、Perpetual，禁止靜默替代或混用。

## Missing／異常資料處理原則

本 Skill 只負責：

```text
Detect
Report
Certify / Reject
```

不負責：

```text
Download
Repair
Interpolation
Resample
Dataset Build
```

不得自行補資料、插值、刪除異常列後直接 PASS、自動更換資料來源或縮短回測期間。

需要修改 Dataset 時，標記為 FAIL／Pending，交給 Data Acquisition／Dataset Maintenance；修改完成後再重新驗證。

## Dataset Manifest

認證成功至少記錄：

```text
dataset_id
version
fingerprint
source
exchange
symbol
market_type
timeframe
timezone
start_time
end_time
row_count
certified_at
integrity_status
```

完整性統計至少記錄：

```text
missing_bars
duplicate_rows
invalid_ohlc
invalid_volume
incomplete_candles
```

認證狀態使用：

```text
PASS
WARNING
FAIL
```

- `PASS`：允許正式使用。
- `WARNING`：必須記錄問題、影響範圍與是否允許正式回測。
- `FAIL`：不得進入正式回測。

## Fingerprint 規則

Fingerprint 用於確認目前 Dataset 是否仍是當初被認證的內容。

回測前的 Fingerprint／Certification 檢查屬於 Backtest Preflight，不屬於本 Skill 的例行工作。

若：

```text
current_fingerprint == certified_fingerprint
```

且 Dataset 已認證，直接回測，不觸發本 Skill。

若不一致，停止回測並以「重新驗證」模式觸發本 Skill。

## Agent／Token 規則

不得讓 LLM 逐筆閱讀大型 OHLCV Dataset。

優先使用本機 Python／SQL／既有 audit 工具完成完整掃描：

```text
Dataset
→ Local Validation
→ Compact Summary
→ Agent Review
```

Agent 預設只讀：

- Validation Summary。
- Dataset Manifest。
- Error／Warning 統計。
- 必要 Metadata。
- 少量異常樣本，通常不超過 20 列。

完整 row-level diagnostics 應保存為本機 artifact，不放入模型 context。

## 責任邊界

- **Backtest Preflight**：確認 Dataset 是否存在、Timeframe／Date Range 是否足夠、是否已認證、Fingerprint 是否一致。
- **Data Acquisition／Dataset Build**：下載、更新、建立不同 Timeframe Dataset、補足日期範圍與資料維護。
- **Data Integrity Review**：驗證已存在 Dataset 的完整性並決定是否認證。
- **Backtest Auditor**：檢查訊號、成交時序、偷看未來與回測邏輯。
- **Execution Cost Review**：檢查 Fee、Slippage、Funding、Leverage、Liquidation 與成交模型。

## 最終規則

```text
新 Dataset 已存在但未認證
→ 使用本 Skill

Dataset 實際內容改變
→ 使用本 Skill

合理懷疑 Dataset 異常
→ 使用本 Skill

Dataset 已認證且內容未變
→ 不使用

策略或參數改變
→ 不使用

缺少 Symbol / Market Type / Timeframe / Date Range
→ 不使用
→ STOP + 要求 Data Acquisition / Dataset Build
```

核心原則：**資料先準備、一次認證、重複使用；資料不變，就不要重複驗證。**
