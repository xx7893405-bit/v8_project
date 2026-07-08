import pandas as pd
from v8_trader import V8_Omniscient_Eye


class V8_Backtester:
    def __init__(self, csv_path, initial_balance=10000.0, risk_pct=0.01):
        self.csv_path = csv_path
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.risk_pct = risk_pct  # 每筆交易風險比例 (例如 1% 帳戶餘額)
        self.trades = []
        self.load_data()

    def load_data(self):
        print(f"載入數據 {self.csv_path}...")
        self.df = pd.read_csv(self.csv_path, index_col="datetime", parse_dates=True)
        # 初始化 V8 指標
        print("計算 V8 系統指標...")
        self.v8 = V8_Omniscient_Eye(self.df)
        self.df_indicators = self.v8.df

    def run(self):
        print("開始執行回測...")
        df = self.df_indicators
        n_rows = len(df)

        active_position = None
        # active_position 格式:
        # {
        #     'type': 'LONG' | 'SHORT',
        #     'entry_time': timestamp,
        #     'entry_price': float,
        #     'sl': float,
        #     'tp1': float,
        #     'tp2': float,
        #     'tp1_hit': bool,
        #     'size': float,
        #     'entry_balance': float
        # }

        # 從第 60 根 K 線開始，因為 MA60 需要 60 根數據，且 SMC 需要至少 20 根歷史
        for i in range(60, n_rows):
            curr = df.iloc[i]
            curr_time = df.index[i]

            # 1. 檢查並更新現有持倉狀態
            if active_position is not None:
                pos_type = active_position["type"]
                entry_price = active_position["entry_price"]
                sl = active_position["sl"]
                tp1 = active_position["tp1"]
                tp2 = active_position["tp2"]
                size = active_position["size"]

                if pos_type == "LONG":
                    # 判斷是否止損
                    if curr["low"] <= sl:
                        # 止損出場
                        # 如果 tp1 已經先到了，表示剩下的 50% 在保本止損（移動至進場價）被掃出場
                        exit_price = sl
                        if active_position["tp1_hit"]:
                            pnl = 0.5 * size * (tp1 - entry_price) + 0.5 * size * (exit_price - entry_price)
                        else:
                            pnl = size * (exit_price - entry_price)

                        self.balance += pnl
                        self.trades.append({
                            "type": "LONG",
                            "entry_time": active_position["entry_time"],
                            "exit_time": curr_time,
                            "entry_price": entry_price,
                            "exit_price": exit_price,
                            "pnl": pnl,
                            "pnl_pct": (pnl / active_position["entry_balance"]) * 100,
                            "result": "BREAKEVEN" if active_position["tp1_hit"] else "STOP_LOSS",
                            "details": "TP1 被觸及後保本出場" if active_position["tp1_hit"] else "觸及止損"
                        })
                        active_position = None

                    # 判斷是否觸及 TP1
                    elif not active_position["tp1_hit"] and curr["high"] >= tp1:
                        active_position["tp1_hit"] = True
                        # 移動止損到進場點 (保本)
                        active_position["sl"] = entry_price
                        # 如果一根 K 線同時衝到 TP2，直接全平
                        if curr["high"] >= tp2:
                            pnl = size * (0.5 * (tp1 - entry_price) + 0.5 * (tp2 - entry_price))
                            self.balance += pnl
                            self.trades.append({
                                "type": "LONG",
                                "entry_time": active_position["entry_time"],
                                "exit_time": curr_time,
                                "entry_price": entry_price,
                                "exit_price": tp2,
                                "pnl": pnl,
                                "pnl_pct": (pnl / active_position["entry_balance"]) * 100,
                                "result": "TAKE_PROFIT_ALL",
                                "details": "一次性觸及 TP1 與 TP2"
                            })
                            active_position = None
                    
                    # 判斷是否觸及 TP2 (在 TP1 已經觸及的情況下)
                    elif active_position is not None and active_position["tp1_hit"] and curr["high"] >= tp2:
                        exit_price = tp2
                        pnl = 0.5 * size * (tp1 - entry_price) + 0.5 * size * (exit_price - entry_price)
                        self.balance += pnl
                        self.trades.append({
                            "type": "LONG",
                            "entry_time": active_position["entry_time"],
                            "exit_time": curr_time,
                            "entry_price": entry_price,
                            "exit_price": exit_price,
                            "pnl": pnl,
                            "pnl_pct": (pnl / active_position["entry_balance"]) * 100,
                            "result": "TAKE_PROFIT_ALL",
                            "details": "TP1 & TP2 全部獲利出場"
                        })
                        active_position = None

                elif pos_type == "SHORT":
                    # 判斷是否止損
                    if curr["high"] >= sl:
                        exit_price = sl
                        if active_position["tp1_hit"]:
                            pnl = 0.5 * size * (entry_price - tp1) + 0.5 * size * (entry_price - exit_price)
                        else:
                            pnl = size * (entry_price - exit_price)

                        self.balance += pnl
                        self.trades.append({
                            "type": "SHORT",
                            "entry_time": active_position["entry_time"],
                            "exit_time": curr_time,
                            "entry_price": entry_price,
                            "exit_price": exit_price,
                            "pnl": pnl,
                            "pnl_pct": (pnl / active_position["entry_balance"]) * 100,
                            "result": "BREAKEVEN" if active_position["tp1_hit"] else "STOP_LOSS",
                            "details": "TP1 被觸及後保本出場" if active_position["tp1_hit"] else "觸及止損"
                        })
                        active_position = None

                    # 判斷是否觸及 TP1
                    elif not active_position["tp1_hit"] and curr["low"] <= tp1:
                        active_position["tp1_hit"] = True
                        # 移動止損到進場點 (保本)
                        active_position["sl"] = entry_price
                        # 如果一根 K 線同時衝到 TP2
                        if curr["low"] <= tp2:
                            pnl = size * (0.5 * (entry_price - tp1) + 0.5 * (entry_price - tp2))
                            self.balance += pnl
                            self.trades.append({
                                "type": "SHORT",
                                "entry_time": active_position["entry_time"],
                                "exit_time": curr_time,
                                "entry_price": entry_price,
                                "exit_price": tp2,
                                "pnl": pnl,
                                "pnl_pct": (pnl / active_position["entry_balance"]) * 100,
                                "result": "TAKE_PROFIT_ALL",
                                "details": "一次性觸及 TP1 與 TP2"
                            })
                            active_position = None

                    # 判斷是否觸及 TP2 (在 TP1 已經觸及的情況下)
                    elif active_position is not None and active_position["tp1_hit"] and curr["low"] <= tp2:
                        exit_price = tp2
                        pnl = 0.5 * size * (entry_price - tp1) + 0.5 * size * (entry_price - exit_price)
                        self.balance += pnl
                        self.trades.append({
                            "type": "SHORT",
                            "entry_time": active_position["entry_time"],
                            "exit_time": curr_time,
                            "entry_price": entry_price,
                            "exit_price": exit_price,
                            "pnl": pnl,
                            "pnl_pct": (pnl / active_position["entry_balance"]) * 100,
                            "result": "TAKE_PROFIT_ALL",
                            "details": "TP1 & TP2 全部獲利出場"
                        })
                        active_position = None

            # 2. 如果沒有持倉，判斷是否產生新信號
            if active_position is None:
                # 獲取 SMC 結構近期歷史 (當前 K 線之前的 19 根 K 線)
                hist = df.iloc[i-19 : i]

                recent_high = hist["high"].max()
                recent_low = hist["low"].min()

                liquidity_sweep_short = (
                    curr["high"] > recent_high and curr["close"] < recent_high
                )
                liquidity_sweep_long = (
                    curr["low"] < recent_low and curr["close"] > recent_low
                )

                # V6 動能驗證
                ma20_status = "高位" if curr["MA20_col"] > curr["close"] else "低位"

                predict_golden_cross = (
                    curr["close"] > curr["MA5"]
                    and curr["close"] > curr["MA5_col"]
                    and curr["MA10_col"] < curr["close"]
                )

                # VWAP 籌碼驗證
                above_vwap = curr["close"] > curr["VWAP"]
                touch_upper_2_0 = curr["high"] >= curr["VWAP_2.0_SD_Upper"]
                touch_lower_2_0 = curr["low"] <= curr["VWAP_2.0_SD_Lower"]

                # 訊號判斷
                # 做空條件
                if liquidity_sweep_short and ma20_status == "高位" and touch_upper_2_0:
                    sl = round(curr["high"] * 1.002, 2)
                    tp1 = round(curr["VWAP"], 2)
                    tp2 = round(curr["VWAP_2.0_SD_Lower"], 2)

                    # 風險管理：計算倉位大小
                    risk_amt = self.balance * self.risk_pct
                    price_risk = sl - curr["close"]
                    if price_risk > 0:
                        size = risk_amt / price_risk
                        active_position = {
                            "type": "SHORT",
                            "entry_time": curr_time,
                            "entry_price": curr["close"],
                            "sl": sl,
                            "tp1": tp1,
                            "tp2": tp2,
                            "tp1_hit": False,
                            "size": size,
                            "entry_balance": self.balance
                        }

                # 做多條件
                elif (
                    liquidity_sweep_long
                    and predict_golden_cross
                    and (touch_lower_2_0 or above_vwap)
                ):
                    sl = round(curr["low"] * 0.998, 2)
                    tp1 = round(curr["VWAP"], 2)
                    tp2 = round(curr["VWAP_2.0_SD_Upper"], 2)

                    # 風險管理：計算倉位大小
                    risk_amt = self.balance * self.risk_pct
                    price_risk = curr["close"] - sl
                    if price_risk > 0:
                        size = risk_amt / price_risk
                        active_position = {
                            "type": "LONG",
                            "entry_time": curr_time,
                            "entry_price": curr["close"],
                            "sl": sl,
                            "tp1": tp1,
                            "tp2": tp2,
                            "tp1_hit": False,
                            "size": size,
                            "entry_balance": self.balance
                        }

        self.print_results()

    def print_results(self):
        print("\n" + "="*50)
        print("📊 V8 全知之眼 - 30天回測報告 (Backtest Report)")
        print("="*50)

        total_trades = len(self.trades)
        if total_trades == 0:
            print("❌ 期間內沒有觸發任何 V8 共振信號。")
            return

        df_trades = pd.DataFrame(self.trades)
        wins = df_trades[df_trades["result"].isin(["TAKE_PROFIT_ALL", "BREAKEVEN"])]
        win_rate = (len(wins) / total_trades) * 100

        # 計算淨利潤
        net_profit = self.balance - self.initial_balance
        profit_pct = (net_profit / self.initial_balance) * 100

        print(f"| 項目 | 回測數據 |")
        print(f"| :--- | :--- |")
        print(f"| 初始資金 | ${self.initial_balance:,.2f} |")
        print(f"| 最終資金 | ${self.balance:,.2f} |")
        print(f"| 累計淨利 | ${net_profit:+,.2f} ({profit_pct:+.2f}%) |")
        print(f"| 總交易筆數 | {total_trades} 筆 |")
        print(f"| 勝率 (觸及 TP1) | {win_rate:.2f}% (包含 TP1 達標後保本出場) |")
        
        # 細分結果
        tp_all = len(df_trades[df_trades["result"] == "TAKE_PROFIT_ALL"])
        be = len(df_trades[df_trades["result"] == "BREAKEVEN"])
        sl_hits = len(df_trades[df_trades["result"] == "STOP_LOSS"])
        
        print(f"| 完整止盈 (TP2) | {tp_all} 筆 |")
        print(f"| 保本出場 (TP1後) | {be} 筆 |")
        print(f"| 完整止損 (SL) | {sl_hits} 筆 |")
        print("="*50)

        print("\n📋 詳細交易日誌 (Trade Log):")
        for i, t in enumerate(self.trades):
            sign = "+" if t["pnl"] >= 0 else ""
            print(f"#{i+1:02d} [{t['entry_time']}] 方向: {t['type']} | 進場: ${t['entry_price']:.2f} -> 出場: ${t['exit_price']:.2f} | 損益: {sign}${t['pnl']:.2f} ({t['pnl_pct']:.2f}%) | 備註: {t['details']}")


if __name__ == "__main__":
    backtester = V8_Backtester("btc_15m_1month.csv")
    backtester.run()
