# NFE 雙級別交易戰法：量化架構與規則解構

本研究報告基於您提供的第一階段摘要，進一步結合 **SMC (Smart Money Concepts，聰明錢概念)** 與 **分形幾何理論**，將「卡魯鴨 Karooduck」的 NFE 體系進行**操作化 (Operationalization) 拆解**，為您整理出可量化的規則與 Python 回測代碼框架。

來源說明：
本文件主要是依據 [Karooduck Trading YouTube 頻道](https://www.youtube.com/@karooduck_trading) 的內容所抽取、整理與形式化後的研究筆記。

---

## NFE 與 SMC 核心概念對齊

根據研究與技術特徵比對，NFE (N-Fractal Edge / Nexus Fractal Emergence) 與現代極其流行的 **SMC (Smart Money Concepts)** 在邏輯上是高度對齊的。

| NFE 術語 | SMC 對應術語 | 數學/程式碼精確定義 |
| :--- | :--- | :--- |
| **N字結構 / 分形** | Swing High/Low & BOS | 市場價格由一波上漲、回調、再突破組成（形成 N 字）。程式碼中定義為波段高低點（Fractal High/Low）的突破。 |
| **級別** | HTF/LTF Structure | 指「結構層級」而非「時間週期」。大級別 N 字的一條邊（單邊波段），在小級別中是完整的數個 N 字結構。 |
| **邊界 / 樞紐** | POI / Order Block (OB) | 價格產生強烈失衡或突破的起點（大級別 Demand/Supply Zone 或 FVG）。是預期產生轉折的邊界。 |
| **結構破壞 / 共振** | CHoCH / iBOS | 當小級別價格觸及大級別邊界時，小級別的 N 字結構方向發生反轉（CHoCH），代表大小級別的方向達成共振。 |
| **反脆弱 (11R/42R)** | High R:R Entry | 用小級別極小停損（防守於小級別新波段低點），博取大級別波段利潤。這正是高盈虧比的數學核心。 |

---

## NFE 雙級別交易戰法：形式化規則

為了將其寫成回測系統，我們必須將其「形式化」為三個主要步驟：

### 1. 進場條件 (Entry Trigger)

- **步驟一（母體定邊界）**
  - 在大級別（如 `H1` 或 `H4`）尋找結構突破（BOS / N字突破）。
  - 標記突破的起點作為**大級別 Order Block (OB)**，此區間 `[Price_high, Price_low]` 即為「邊界」。
- **步驟二（共振觸發）**
  - 當價格回踩大級別 OB 區間時，將分析級別切換至小級別（如 `M5` 或 `M15`）。
  - 等待小級別產生 **CHoCH (Change of Character)**：即小級別的最後一個看跌波段高點（Strong High）被向上收盤突破。
- **步驟三（掛單進場）**
  - 小級別 CHoCH 發生後，會在此突破波段起點產生一個**小級別新 OB**。
  - 在小級別新 OB 的上沿放置買入限制單（Limit Order）等待回踩進場。

### 2. 出場與防守條件 (Exit & Risk Management)

- **停損 (Stop Loss)**
  - 設定在小級別 CHoCH 形成的**最新 Swing Low 下方 1-2 點**。
- **停利 (Take Profit)**
  - **第一目標 (TP1)**：大級別 N字結構的前高（波段阻力點），完成大部分倉位止盈。
  - **移動止盈 (Trailing Stop)**：保留小部分倉位，以大級別的 N字結構不被破壞（不跌破大級別 Swing Low）為原則持倉，博取波段延伸。

---

## 量化特徵欄位與策略偽代碼

要將 NFE 整理成代碼，首先需要計算**波段高低點（Swing High / Swing Low）**。我們可以用 Python 實作一個「N字結構與分形檢測器」。

### 1. 特徵欄位定義

- `is_swing_high / is_swing_low`：用 Window Size（例如左右各看 `N` 根 K 線）標記局部波谷波峰。
- `BOS_occurred`：當前價格突破上一個 Swing High（看漲）或跌破上一個 Swing Low（看跌）。
- `POI_zone`：當發生 BOS 時，前一個 Swing Low 到該 K 線實體最低點的區間（定義為大級別 OB 邊界）。

### 2. 策略偽代碼 (Python 邏輯)

```python
def check_nfe_strategy(df_htf, df_ltf):
    # df_htf: 大級別 DataFrame (例如 1H)
    # df_ltf: 小級別 DataFrame (例如 5M)

    # 1. 在大級別尋找 POI 邊界
    htf_swings = find_swing_points(df_htf)
    latest_bos = detect_bos(df_htf, htf_swings)

    if latest_bos and is_price_in_zone(df_ltf["close"].iloc[-1], latest_bos["poi_zone"]):
        # 價格已回踩大級別邊界，啟動小級別監控
        ltf_swings = find_swing_points(df_ltf)

        # 2. 監控小級別結構破壞 (CHoCH)
        if detect_choch(df_ltf, ltf_swings, direction="up"):
            entry_price = ltf_swings["latest_ob_high"]
            stop_loss = ltf_swings["latest_swing_low"] - tick_size
            take_profit = latest_bos["target_high"]

            risk = entry_price - stop_loss
            reward = take_profit - entry_price
            r_ratio = reward / risk

            # 3. 確保盈虧比大於臨界值（如反脆弱要求的高R比）
            if r_ratio >= 5.0:
                return {
                    "action": "BUY_LIMIT",
                    "entry": entry_price,
                    "sl": stop_loss,
                    "tp": take_profit,
                    "r_ratio": r_ratio,
                }
    return None
```
