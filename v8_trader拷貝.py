import sys
import os

# 自動檢測並切換至虛擬環境 (防止用戶直接執行系統 python 出現 No module named numpy)
try:
    import numpy as np
    import pandas as pd
except ImportError:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    venv_python = os.path.join(current_dir, "venv", "bin", "python")
    if not os.path.exists(venv_python):
        venv_python = os.path.join(current_dir, "v8_project", "venv", "bin", "python")
    
    if os.path.exists(venv_python):
        os.execv(venv_python, [venv_python] + sys.argv)
    else:
        print("❌ 錯誤: 找不到已安裝依賴的虛擬環境 'venv'，請先在 v8_project 目錄下建立虛擬環境。")
        sys.exit(1)


class V8_Omniscient_Eye:
    """V8 全知之眼 - 加密貨幣頂級交易系統

    融合 SMC (空間)、V6 (時間動能)、VWAP (真實籌碼) 的三維共振交易內核。
    """

    def __init__(self, df):
        """傳入包含高開低收量 (OHLCV) 的 pandas DataFrame

        必備欄位: 'open', 'high', 'low', 'close', 'volume'
        """
        self.df = df.copy()
        self._calculate_indicators()

    def _calculate_indicators(self):
        """計算 V6 (均線與扣抵) 與 VWAP 指標"""
        # 1. V6 動能指標計算
        self.df["MA5"] = self.df["close"].rolling(window=5).mean()
        self.df["MA10"] = self.df["close"].rolling(window=10).mean()
        self.df["MA20"] = self.df["close"].rolling(window=20).mean()
        self.df["MA60"] = self.df["close"].rolling(window=60).mean()

        # 標記扣抵值 (Ref 指向歷史對應位置的價格)
        self.df["MA5_col"] = self.df["close"].shift(4)
        self.df["MA10_col"] = self.df["close"].shift(9)
        self.df["MA20_col"] = self.df["close"].shift(19)
        self.df["MA60_col"] = self.df["close"].shift(59)

        # 2. VWAP 籌碼指標計算 (以當前全數據或典型日內滾動計算)
        typical_price = (self.df["high"] + self.df["low"] + self.df["close"]) / 3
        v_tp = typical_price * self.df["volume"]

        self.df["VWAP"] = v_tp.cumsum() / self.df["volume"].cumsum()

        # 計算隨時間累積的標準差 (SD)
        variance = (typical_price - self.df["VWAP"]) ** 2
        v_var = variance * self.df["volume"]
        cum_v_var = v_var.cumsum() / self.df["volume"].cumsum()
        self.df["VWAP_SD"] = np.sqrt(cum_v_var)

        # 邊界定義
        self.df["VWAP_1.0_SD_Upper"] = self.df["VWAP"] + self.df["VWAP_SD"]
        self.df["VWAP_1.0_SD_Lower"] = self.df["VWAP"] - self.df["VWAP_SD"]
        self.df["VWAP_2.0_SD_Upper"] = self.df["VWAP"] + (
            self.df["VWAP_SD"] * 2
        )
        self.df["VWAP_2.0_SD_Lower"] = self.df["VWAP"] - (
            self.df["VWAP_SD"] * 2
        )

    def analyze_market(self):
        """執行四層運算邏輯，輸出 V8 決策與報告"""
        # 獲取當前最新 K 線數據
        curr = self.df.iloc[-1]
        hist = self.df.iloc[-20:-1]  # 用於判斷 SMC 結構的近期歷史

        # --- 第一層：SMC 結構定位 (簡化算法模擬) ---
        recent_high = hist["high"].max()
        recent_low = hist["low"].min()

        liquidity_sweep_short = (
            curr["high"] > recent_high and curr["close"] < recent_high
        )
        liquidity_sweep_long = (
            curr["low"] < recent_low and curr["close"] > recent_low
        )

        # --- 第二層：V6 動能驗證 ---
        # MA20 扣抵狀態
        ma20_status = (
            "高位" if curr["MA20_col"] > curr["close"] else "低位"
        )
        ma20_trend = "蓋頭下壓" if ma20_status == "高位" else "向上支撐"

        # MA5/MA10 預判金死叉
        predict_golden_cross = (
            curr["close"] > curr["MA5"]
            and curr["close"] > curr["MA5_col"]
            and curr["MA10_col"] < curr["close"]
        )
        predict_death_cross = (
            curr["close"] < curr["MA5"]
            and curr["close"] < curr["MA5_col"]
            and curr["MA10_col"] > curr["close"]
        )

        # --- 第三層：VWAP 籌碼驗證 ---
        above_vwap = curr["close"] > curr["VWAP"]
        touch_upper_2_0 = curr["high"] >= curr["VWAP_2.0_SD_Upper"]
        touch_lower_2_0 = curr["low"] <= curr["VWAP_2.0_SD_Lower"]

        # --- 第四層：V8 綜合決策過濾器 ---
        strategy = "觀望 WAIT"
        reason = "結構與籌碼未達成三維共振，嚴格觀望。"
        sl, tp1, tp2, rr = 0, 0, 0, 0

        # 做空條件：SMC 掠奪高點 + V6 蓋頭 + VWAP 觸碰超買極端值
        if liquidity_sweep_short and ma20_status == "高位" and touch_upper_2_0:
            strategy = "做空 SHORT"
            reason = (
                "SMC 掠奪完成 + V6 鋼板壓力 + VWAP 2.0 SD 極端值阻力"
            )
            sl = round(curr["high"] * 1.002, 2)  # 針尖上方 0.2% 防守
            tp1 = round(curr["VWAP"], 2)  # 均值回歸中軌
            tp2 = round(curr["VWAP_2.0_SD_Lower"], 2)  # 下軌
            rr = round((curr["close"] - tp1) / (sl - curr["close"]), 1)

        # 做多條件：SMC 掠奪低點 + V6 預判金叉 + VWAP 觸碰超賣極端值/站穩
        elif (
            liquidity_sweep_long
            and predict_golden_cross
            and (touch_lower_2_0 or above_vwap)
        ):
            strategy = "做多 LONG"
            reason = "SMC 針尖掠奪 + V6 預判金叉 + 站穩 VWAP 核心價值區"
            sl = round(curr["low"] * 0.998, 2)
            tp1 = round(curr["VWAP"], 2)
            tp2 = round(curr["VWAP_2.0_SD_Upper"], 2)
            rr = round((tp1 - curr["close"]) / (curr["close"] - sl), 1)

        # --- 輸出格式化報告 ---
        output = f"""
🎯 V8 狙擊策略單 (V8 Sniper Setup)
| 項目 | 內容 |
| :--- | :--- |
| 策略方向 | **{strategy}** |
| 進場區域 | ${round(curr['close'], 2)} (依據：{reason}) |
| 止損 (SL) | ${sl if sl else '----'} (嚴格防守結構針尖或實體跌破 VWAP) |
| 止盈 (TP) | TP1: ${tp1 if tp1 else '----'} (VWAP 中軌均值回歸)<br><br>TP2: ${tp2 if tp2 else '----'} (極端標準差區間) |
| 盈虧比 (RR)| 1 : {rr if rr else '----'} |

👁️ 未來 30m-60m 看盤重點 (Immediate Focus)
* **關鍵價位與籌碼監控**：若價格觸及 ${round(curr['VWAP'], 2)}，需觀察是否帶量突破 VWAP。若無法站穩均價線，且 MA5/10 呈現 [{"預判死叉" if predict_death_cross else "正常形態"}]，則確認為假突破 (Fakeout)。
* **V6 動能預判**：MA20 目前扣抵 {ma20_status} (${round(curr['MA20_col'], 2)})，均線呈現 [{ma20_trend}]。預計未來 3 根 K 線動能將 [{"減弱" if ma20_status == "高位" else "增強"}]。
* **VWAP 引力警示**：目前價格偏離 VWAP [{"已達到" if (touch_upper_2_0 or touch_lower_2_0) else "未達"}] 極端標準差 (SD) 區間，注意 ${round(curr['VWAP'], 2)} 附近的 [均值回歸] 引力，若出現長針速回，立即評估反轉。
"""
        print(output)


# ==========================================
# 模擬測試數據 (模擬 BTC 觸及高位假突破歸位情境)
# ==========================================
if __name__ == "__main__":
    np.random.seed(42)
    data_length = 100
    dates = pd.date_range(start="2026-07-06", periods=data_length, freq="15min")

    # 建立基礎隨機走勢
    close_prices = 60000 + np.cumsum(np.random.randn(data_length) * 100)
    high_prices = close_prices + np.random.rand(data_length) * 50
    low_prices = close_prices - np.random.rand(data_length) * 50
    open_prices = close_prices - np.random.randn(data_length) * 30
    volumes = np.random.randint(100, 1000, size=data_length)

    mock_df = pd.DataFrame(
        {
            "open": open_prices,
            "high": high_prices,
            "low": low_prices,
            "close": close_prices,
            "volume": volumes,
        },
        index=dates,
    )

    # 人為製造一個完美符合「做空 SHORT」的 V8 訊號節點 (最後一根 K 線)
    mock_df.loc[mock_df.index[-1], "high"] = 62500  # 突破歷史前高
    mock_df.loc[mock_df.index[-1], "close"] = 61800  # 快速收回
    mock_df.loc[mock_df.index[-1], "MA20_col"] = 63000  # 扣抵高位

    # 執行 V8 引擎
    v8_trader = V8_Omniscient_Eye(mock_df)
    v8_trader.analyze_market()
