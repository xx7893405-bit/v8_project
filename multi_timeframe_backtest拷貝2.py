import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# V8 全知之眼 - 防污染、完全實盤對齊運算內核
# ---------------------------------------------------------------------------
class V8_Omniscient_Eye:
    def __init__(self, df):
        self.df = df.copy()
        self.calculate_v8_indicators()
    
    def calculate_v8_indicators(self):
        df_dt = self.df.copy()
        df_dt['date'] = df_dt.index.date
        df_dt['pv'] = df_dt['close'] * df_dt['volume']
        
        cum_pv = df_dt.groupby('date')['pv'].cumsum()
        cum_v = df_dt.groupby('date')['volume'].cumsum()
        self.df['VWAP'] = cum_pv / cum_v
        
        rolling_std = df_dt['close'].rolling(96, min_periods=1).std()
        self.df['VWAP_SD'] = rolling_std
        self.df['VWAP_1.0_SD_Upper'] = self.df['VWAP'] + rolling_std
        self.df['VWAP_1.0_SD_Lower'] = self.df['VWAP'] - rolling_std
        self.df['VWAP_2.0_SD_Upper'] = self.df['VWAP'] + (rolling_std * 2.0)
        self.df['VWAP_2.0_SD_Lower'] = self.df['VWAP'] - (rolling_std * 2.0)
        
        self.df['MA5'] = self.df['close'].rolling(5).mean()
        self.df['MA10'] = self.df['close'].rolling(10).mean()
        self.df['MA20'] = self.df['close'].rolling(20).mean()
        self.df['MA20_Ref'] = self.df['close'].shift(20)
        
        self.df['local_bias'] = np.where((self.df['close'] > self.df['MA20']) & (self.df['close'] > self.df['MA20_Ref']), "LONG",
                                         np.where((self.df['close'] < self.df['MA20']) & (self.df['close'] < self.df['MA20_Ref']), "SHORT", "NONE"))


def calculate_realtime_fvg(df):
    df = df.copy()
    fvg_type = [None] * len(df)
    fvg_top = [np.nan] * len(df)
    fvg_bottom = [np.nan] * len(df)
    
    active_bullish_fvgs = []
    active_bearish_fvgs = []
    
    for i in range(2, len(df)):
        p_prev = df.iloc[i-2]
        p_curr = df.iloc[i-1]
        p_next = df.iloc[i]
        
        if p_next['low'] > p_prev['high']:
            active_bullish_fvgs.append({'top': p_next['low'], 'bottom': p_prev['high']})
        elif p_next['high'] < p_prev['low']:
            active_bearish_fvgs.append({'top': p_prev['low'], 'bottom': p_next['high']})
            
        current_close = p_next['close']
        active_bullish_fvgs = [f for f in active_bullish_fvgs if current_close >= f['bottom']]
        active_bearish_fvgs = [f for f in active_bearish_fvgs if current_close <= f['top']]
        
        if active_bullish_fvgs:
            latest = active_bullish_fvgs[-1]
            fvg_type[i] = "BULLISH"
            fvg_top[i] = latest['top']
            fvg_bottom[i] = latest['bottom']
        elif active_bearish_fvgs:
            latest = active_bearish_fvgs[-1]
            fvg_type[i] = "BEARISH"
            fvg_top[i] = latest['top']
            fvg_bottom[i] = latest['bottom']
            
    df['fvg_type'] = fvg_type
    df['fvg_top'] = fvg_top
    df['fvg_bottom'] = fvg_bottom
    return df[['fvg_type', 'fvg_top', 'fvg_bottom']]


class MultiTimeframeBacktester:
    def __init__(self, initial_balance=10000.0, risk_pct=0.01):
        self.initial_balance = initial_balance
        self.risk_pct = risk_pct
        self.load_all_data()

    def load_all_data(self):
        print("正在載入多時段歷史數據...")
        self.df_15m = pd.read_csv("btc_15m.csv", index_col="datetime", parse_dates=True).sort_index()
        self.df_1h = pd.read_csv("btc_1h.csv", index_col="datetime", parse_dates=True).sort_index()
        self.df_4h = pd.read_csv("btc_4h.csv", index_col="datetime", parse_dates=True).sort_index()
        self.df_1d = pd.read_csv("btc_1d.csv", index_col="datetime", parse_dates=True).sort_index()

        for df in [self.df_15m, self.df_1h, self.df_4h, self.df_1d]:
            df.index = pd.to_datetime(df.index).tz_localize(None)

        print("正在注入大時區 V6 燃料扣抵...")
        for df in [self.df_1d, self.df_4h]:
            df["MA20"] = df["close"].rolling(20).mean()
            df["MA20_Ref"] = df["close"].shift(20)
            df["bias"] = np.where((df["close"] > df["MA20"]) & (df["close"] > df["MA20_Ref"]), "LONG", 
                                  np.where((df["close"] < df["MA20"]) & (df["close"] < df["MA20_Ref"]), "SHORT", "NONE"))

        print("正在計算具有【動態緩解】的機構失衡區 (FVG)...")
        df_1h_fvg = calculate_realtime_fvg(self.df_1h)
        df_15m_fvg = calculate_realtime_fvg(self.df_15m)
        
        print("正在建構 15m 全知指標矩陣...")
        self.v8_15m = V8_Omniscient_Eye(self.df_15m)
        df_res = self.v8_15m.df

        df_res["m15_fvg_type"] = df_15m_fvg["fvg_type"]
        df_res["m15_fvg_top"] = df_15m_fvg["fvg_top"]
        df_res["m15_fvg_bottom"] = df_15m_fvg["fvg_bottom"]

        print("正在執行多時區時間軸【嚴格右側對齊】...")
        df_res["bias_1d"] = self.df_1d["bias"].reindex(df_res.index, method="ffill").shift(96)
        df_res["bias_4h"] = self.df_4h["bias"].reindex(df_res.index, method="ffill").shift(16)
        
        df_res["h1_fvg_type"] = df_1h_fvg["fvg_type"].reindex(df_res.index, method="ffill").shift(4)
        df_res["h1_fvg_top"] = df_1h_fvg["fvg_top"].reindex(df_res.index, method="ffill").shift(4)
        df_res["h1_fvg_bottom"] = df_1h_fvg["fvg_bottom"].reindex(df_res.index, method="ffill").shift(4)

        df_res["is_fvg_overlap_long"] = (df_res["m15_fvg_type"] == "BULLISH") & (df_res["h1_fvg_type"] == "BULLISH") & \
                                        ((df_res["m15_fvg_bottom"] <= df_res["h1_fvg_top"]) & (df_res["m15_fvg_top"] >= df_res["h1_fvg_bottom"]))

        df_res["is_fvg_overlap_short"] = (df_res["m15_fvg_type"] == "BEARISH") & (df_res["h1_fvg_type"] == "BEARISH") & \
                                         ((df_res["m15_fvg_top"] >= df_res["h1_fvg_bottom"]) & (df_res["m15_fvg_bottom"] <= df_res["h1_fvg_top"]))

        self.df_15m_indicators = df_res
        print("💡 V8 頂級交易員抗噪重疊引擎封裝完畢。")

    def run_backtest(self, mode="NONE"):
        balance = self.initial_balance
        trades = []
        missed_trades_count = 0  # 👈 核心新增：踏空計數器
        
        df = self.df_15m_indicators
        n_rows = len(df)

        active_position = None
        lookback = 96 

        for i in range(lookback, n_rows):
            curr = df.iloc[i]
            curr_time = df.index[i]

            # 持倉常規管理
            if active_position is not None:
                pos_type = active_position["type"]
                entry_price = active_position["entry_price"]
                sl = active_position["sl"]
                tp1 = active_position["tp1"]
                tp2 = active_position["tp2"]
                size = active_position["size"]
                rr_potential = active_position["rr_potential"]

                if pos_type == "LONG":
                    if curr["low"] <= sl:
                        exit_price = sl
                        pnl = ((0.5 * size * (tp1 - entry_price) + 0.5 * size * (exit_price - entry_price))
                               if active_position["tp1_hit"] else size * (exit_price - entry_price))
                        balance += pnl
                        trades.append({
                            "type": "LONG", "entry_time": active_position["entry_time"], "exit_time": curr_time,
                            "entry_price": entry_price, "exit_price": exit_price, "pnl": pnl,
                            "pnl_pct": (pnl / active_position["entry_balance"]) * 100,
                            "result": "BREAKEVEN" if active_position["tp1_hit"] else "STOP_LOSS", "rr": rr_potential
                        })
                        active_position = None
                    elif not active_position["tp1_hit"] and curr["high"] >= tp1:
                        active_position["tp1_hit"] = True
                        active_position["sl"] = entry_price 
                        if curr["high"] >= tp2:
                            pnl = size * (0.5 * (tp1 - entry_price) + 0.5 * (tp2 - entry_price))
                            balance += pnl
                            trades.append({
                                "type": "LONG", "entry_time": active_position["entry_time"], "exit_time": curr_time,
                                "entry_price": entry_price, "exit_price": tp2, "pnl": pnl,
                                "pnl_pct": (pnl / active_position["entry_balance"]) * 100, "result": "TAKE_PROFIT_ALL", "rr": rr_potential
                            })
                            active_position = None
                    elif active_position is not None and active_position["tp1_hit"] and curr["high"] >= tp2:
                        exit_price = tp2
                        pnl = 0.5 * size * (tp1 - entry_price) + 0.5 * size * (exit_price - entry_price)
                        balance += pnl
                        trades.append({
                            "type": "LONG", "entry_time": active_position["entry_time"], "exit_time": curr_time,
                            "entry_price": entry_price, "exit_price": exit_price, "pnl": pnl,
                            "pnl_pct": (pnl / active_position["entry_balance"]) * 100, "result": "TAKE_PROFIT_ALL", "rr": rr_potential
                        })
                        active_position = None

                elif pos_type == "SHORT":
                    if curr["high"] >= sl:
                        exit_price = sl
                        pnl = ((0.5 * size * (entry_price - tp1) + 0.5 * size * (entry_price - exit_price))
                               if active_position["tp1_hit"] else size * (entry_price - exit_price))
                        balance += pnl
                        trades.append({
                            "type": "SHORT", "entry_time": active_position["entry_time"], "exit_time": curr_time,
                            "entry_price": entry_price, "exit_price": exit_price, "pnl": pnl,
                            "pnl_pct": (pnl / active_position["entry_balance"]) * 100,
                            "result": "BREAKEVEN" if active_position["tp1_hit"] else "STOP_LOSS", "rr": rr_potential
                        })
                        active_position = None
                    elif not active_position["tp1_hit"] and curr["low"] <= tp1:
                        active_position["tp1_hit"] = True
                        active_position["sl"] = entry_price
                        if curr["low"] <= tp2:
                            pnl = size * (0.5 * (entry_price - tp1) + 0.5 * (entry_price - tp2))
                            balance += pnl
                            trades.append({
                                "type": "SHORT", "entry_time": active_position["entry_time"], "exit_time": curr_time,
                                "entry_price": entry_price, "exit_price": tp2, "pnl": pnl,
                                "pnl_pct": (pnl / active_position["entry_balance"]) * 100, "result": "TAKE_PROFIT_ALL", "rr": rr_potential
                            })
                            active_position = None
                    elif active_position is not None and active_position["tp1_hit"] and curr["low"] <= tp2:
                        exit_price = tp2
                        pnl = 0.5 * size * (entry_price - tp1) + 0.5 * size * (entry_price - exit_price)
                        balance += pnl
                        trades.append({
                            "type": "SHORT", "entry_time": active_position["entry_time"], "exit_time": curr_time,
                            "entry_price": entry_price, "exit_price": exit_price, "pnl": pnl,
                            "pnl_pct": (pnl / active_position["entry_balance"]) * 100, "result": "TAKE_PROFIT_ALL", "rr": rr_potential
                        })
                        active_position = None

            # 交易信號觸發與踏空追蹤
            if active_position is None:
                bias_1d = curr["bias_1d"]
                bias_4h = curr["bias_4h"]
                fvg_overlap_long = curr["is_fvg_overlap_long"]
                fvg_overlap_short = curr["is_fvg_overlap_short"]
                h1_top = curr["h1_fvg_top"]
                h1_bottom = curr["h1_fvg_bottom"]

                allowed_long = True
                allowed_short = True
                if mode == "4H":
                    if bias_4h != "LONG": allowed_long = False
                    if bias_4h != "SHORT": allowed_short = False
                elif mode == "4H_1D":
                    if bias_4h != "LONG" or bias_1d != "LONG": allowed_long = False
                    if bias_4h != "SHORT" or bias_1d != "SHORT": allowed_short = False

                # --- 多頭邏輯判斷 ---
                if allowed_long and fvg_overlap_long and pd.notna(h1_top):
                    # 篩選出：結構與籌碼全部符合進場標準的「潛在黃金狙擊點」
                    if (curr["close"] > curr["VWAP"]) and (curr["local_bias"] == "LONG"):
                        entry_p = h1_top
                        sl = round(h1_bottom - 30, 2)
                        tp1 = round(curr["VWAP_1.0_SD_Upper"], 2)
                        
                        # 情況 A：價格成功下踩到掛單點 -> 完美吃單進場
                        if curr["low"] <= entry_p:
                            if curr["close"] > sl and tp1 > entry_p:
                                tp2 = round(curr["VWAP_2.0_SD_Upper"], 2)
                                rr_potential = (tp2 - entry_p) / (entry_p - sl)
                                size = (balance * self.risk_pct) / (entry_p - sl)
                                active_position = {
                                    "type": "LONG", "entry_time": curr_time, "entry_price": entry_p,
                                    "sl": sl, "tp1": tp1, "tp2": tp2, "tp1_hit": False, "size": size, 
                                    "entry_balance": balance, "rr_potential": rr_potential
                                }
                        # 情況 B：價格沒踩到掛單點 (low > entry_p)，但隨後直接噴過原定的 TP1 邊界 -> 判定為踏空！
                        elif curr["low"] > entry_p and curr["high"] >= tp1:
                            missed_trades_count += 1

                # --- 空頭邏輯判斷 ---
                elif allowed_short and fvg_overlap_short and pd.notna(h1_bottom):
                    if (curr["close"] < curr["VWAP"]) and (curr["local_bias"] == "SHORT"):
                        entry_p = h1_bottom
                        sl = round(h1_top + 30, 2)
                        tp1 = round(curr["VWAP_1.0_SD_Lower"], 2)
                        
                        # 情況 A：價格成功上探到掛單點 -> 完美吃單進場
                        if curr["high"] >= entry_p:
                            if curr["close"] < sl and tp1 < entry_p:
                                tp2 = round(curr["VWAP_2.0_SD_Lower"], 2)
                                rr_potential = (entry_p - tp2) / (sl - entry_p)
                                size = (balance * self.risk_pct) / (sl - entry_p)
                                active_position = {
                                    "type": "SHORT", "entry_time": curr_time, "entry_price": entry_p,
                                    "sl": sl, "tp1": tp1, "tp2": tp2, "tp1_hit": False, "size": size, 
                                    "entry_balance": balance, "rr_potential": rr_potential
                                }
                        # 情況 B：價格沒點到掛單點 (high < entry_p)，但隨後直接跌破原定 TP1 邊界 -> 判定為踏空！
                        elif curr["high"] < entry_p and curr["low"] <= tp1:
                            missed_trades_count += 1

        total_trades = len(trades)
        if total_trades == 0:
            return {"trades": 0, "win_rate": 0.0, "profit": 0.0, "balance": balance, "tp_all": 0, "be": 0, "sl": 0, "avg_rr": 0.0, "missed": missed_trades_count}

        df_trades = pd.DataFrame(trades)
        wins = df_trades[df_trades["result"].isin(["TAKE_PROFIT_ALL", "BREAKEVEN"])]
        avg_rr = df_trades["rr"].mean()
        
        return {
            "trades": total_trades, "win_rate": (len(wins) / total_trades) * 100, "profit": ((balance - self.initial_balance) / self.initial_balance) * 100, "balance": balance,
            "tp_all": len(df_trades[df_trades["result"] == "TAKE_PROFIT_ALL"]),
            "be": len(df_trades[df_trades["result"] == "BREAKEVEN"]),
            "sl": len(df_trades[df_trades["result"] == "STOP_LOSS"]),
            "avg_rr": avg_rr,
            "missed": missed_trades_count  # 👈 寫入回報字典
        }

if __name__ == "__main__":
    try:
        backtester = MultiTimeframeBacktester()
        modes = [
            {"name": "15m + 1H FVG 空間重疊 (無污染左側單)", "key": "NONE"},
            {"name": "15m + 1H + 4H 三重共振 (頂級真實防禦)", "key": "4H"},
        ]

        results = []
        for m in modes:
            res = backtester.run_backtest(m["key"])
            results.append({
                "模式": m["name"], "實質交易": res["trades"], "踏空次數": res["missed"], # 👈 輸出看板新增
                "平均盈虧比": f"1 : {res['avg_rr']:.2f}", "勝率(TP1)": f"{res['win_rate']:.2f}%", 
                "獲利(TP2)": res["tp_all"], "保本(BE)": res["be"], "止損(SL)": res["sl"],
                "帳戶淨值": f"${res['balance']:,.2f}", "總損益": f"{res['profit']:+.2f}%"
            })

        pd.set_option('display.unicode.east_asian_width', True) 
        df_results = pd.DataFrame(results)
        print("\n" + "═"*120)
        print(" 📊  V8 全知之眼 - 修正型跨時區 FVG 空間重疊真實回測報告 (導入踏空計數追蹤)")
        print("═"*120)
        print(df_results.to_string(index=False, justify='center'))
        print("═"*120)
    except FileNotFoundError as e:
        print(f"❌ 錯誤：請確保回測數據檔案放置於當前目錄。系統詳情: {e}")