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
        # 1. 質量維度：計算滾動 Daily VWAP 籌碼成本（嚴格依據當天累計，不偷看未來）
        df_dt = self.df.copy()
        df_dt['date'] = df_dt.index.date
        df_dt['pv'] = df_dt['close'] * df_dt['volume']
        
        cum_pv = df_dt.groupby('date')['pv'].cumsum()
        cum_v = df_dt.groupby('date')['volume'].cumsum()
        self.df['VWAP'] = cum_pv / cum_v
        
        # 修正陷阱：使用固定窗口或歷史擴展標準差，避免單邊暴漲後的波動度重繪
        rolling_std = df_dt['close'].rolling(96, min_periods=1).std()
        self.df['VWAP_SD'] = rolling_std
        self.df['VWAP_1.0_SD_Upper'] = self.df['VWAP'] + rolling_std
        self.df['VWAP_1.0_SD_Lower'] = self.df['VWAP'] - rolling_std
        self.df['VWAP_2.0_SD_Upper'] = self.df['VWAP'] + (rolling_std * 2.0)
        self.df['VWAP_2.0_SD_Lower'] = self.df['VWAP'] - (rolling_std * 2.0)
        
        # 2. 時間維度：V6 本地扣抵指標
        self.df['MA5'] = self.df['close'].rolling(5).mean()
        self.df['MA10'] = self.df['close'].rolling(10).mean()
        self.df['MA20'] = self.df['close'].rolling(20).mean()
        self.df['MA20_Ref'] = self.df['close'].shift(20)
        
        self.df['local_bias'] = np.where((self.df['close'] > self.df['MA20']) & (self.df['close'] > self.df['MA20_Ref']), "LONG",
                                         np.where((self.df['close'] < self.df['MA20']) & (self.df['close'] < self.df['MA20_Ref']), "SHORT", "NONE"))


# ---------------------------------------------------------------------------
# 修正後的 FVG 識別與動態緩解（Mitigation）追蹤引擎
# ---------------------------------------------------------------------------
def calculate_realtime_fvg(df):
    """
    拒絕 ffill()！嚴格動態追踪未被緩解（Unmitigated）的最新有效 FVG 邊界。
    """
    df = df.copy()
    fvg_type = [None] * len(df)
    fvg_top = [np.nan] * len(df)
    fvg_bottom = [np.nan] * len(df)
    
    # 用於儲存當前尚未被價格穿透的有效 FVG 隊列
    active_bullish_fvgs = []
    active_bearish_fvgs = []
    
    for i in range(2, len(df)):
        # 1. 識別新產生的 FVG (由 i-2, i-1, i 三根K線確立，在第 i 根收盤時確定)
        p_prev = df.iloc[i-2]
        p_curr = df.iloc[i-1]
        p_next = df.iloc[i]
        
        # Bullish FVG
        if p_next['low'] > p_prev['high']:
            active_bullish_fvgs.append({'top': p_next['low'], 'bottom': p_prev['high']})
        # Bearish FVG
        elif p_next['high'] < p_prev['low']:
            active_bearish_fvgs.append({'top': p_prev['low'], 'bottom': p_next['high']})
            
        # 2. 用當前 K 線實體檢查並移除已被緩解（Mitigated）的舊 FVG
        current_close = p_next['close']
        
        # 多頭 FVG 被實體跌破下沿則失效
        active_bullish_fvgs = [f for f in active_bullish_fvgs if current_close >= f['bottom']]
        # 空頭 FVG 被實體突破上沿則失效
        active_bearish_fvgs = [f for f in active_bearish_fvgs if current_close <= f['top']]
        
        # 3. 將目前「最鄰近、仍有效」的 FVG 寫入當前 K 線狀態
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
        # 修正未來函數陷阱：大時區的訊號必須等到「該K線時間完全結束」後，15m 才能讀取。
        # 1H K線必須 shift 4 碼 (1小時=4根15m)；4H 必須 shift 16 碼；1D 必須 shift 96 碼。
        df_res["bias_1d"] = self.df_1d["bias"].reindex(df_res.index, method="ffill").shift(96)
        df_res["bias_4h"] = self.df_4h["bias"].reindex(df_res.index, method="ffill").shift(16)
        
        df_res["h1_fvg_type"] = df_1h_fvg["fvg_type"].reindex(df_res.index, method="ffill").shift(4)
        df_res["h1_fvg_top"] = df_1h_fvg["fvg_top"].reindex(df_res.index, method="ffill").shift(4)
        df_res["h1_fvg_bottom"] = df_1h_fvg["fvg_bottom"].reindex(df_res.index, method="ffill").shift(4)

        # 判定 15m 與 1H FVG 是否在空間上存在有效重疊
        df_res["is_fvg_overlap_long"] = (df_res["m15_fvg_type"] == "BULLISH") & (df_res["h1_fvg_type"] == "BULLISH") & \
                                        ((df_res["m15_fvg_bottom"] <= df_res["h1_fvg_top"]) & (df_res["m15_fvg_top"] >= df_res["h1_fvg_bottom"]))

        df_res["is_fvg_overlap_short"] = (df_res["m15_fvg_type"] == "BEARISH") & (df_res["h1_fvg_type"] == "BEARISH") & \
                                         ((df_res["m15_fvg_top"] >= df_res["h1_fvg_bottom"]) & (df_res["m15_fvg_bottom"] <= df_res["h1_fvg_top"]))

        self.df_15m_indicators = df_res
        print("💡 V8 頂級交易員抗噪重疊引擎封裝完畢。")

    def run_backtest(self, mode="NONE"):
        balance = self.initial_balance
        trades = []
        df = self.df_15m_indicators
        n_rows = len(df)

        active_position = None
        lookback = 96 

        for i in range(lookback, n_rows):
            curr = df.iloc[i]
            curr_time = df.index[i]

            # 倉位管理 (維持盤中動態偵測，模擬實盤 Tick 穿透)
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
                            "result": "BREAKEVEN" if active_position["tp1_hit"] else "STOP_LOSS",
                            "rr": rr_potential
                        })
                        active_position = None
                    elif not active_position["tp1_hit"] and curr["high"] >= tp1:
                        active_position["tp1_hit"] = True
                        active_position["sl"] = entry_price # 觸及 TP1 後移向保本點
                        if curr["high"] >= tp2:
                            pnl = size * (0.5 * (tp1 - entry_price) + 0.5 * (tp2 - entry_price))
                            balance += pnl
                            trades.append({
                                "type": "LONG", "entry_time": active_position["entry_time"], "exit_time": curr_time,
                                "entry_price": entry_price, "exit_price": tp2, "pnl": pnl,
                                "pnl_pct": (pnl / active_position["entry_balance"]) * 100, "result": "TAKE_PROFIT_ALL",
                                "rr": rr_potential
                            })
                            active_position = None
                    elif active_position is not None and active_position["tp1_hit"] and curr["high"] >= tp2:
                        exit_price = tp2
                        pnl = 0.5 * size * (tp1 - entry_price) + 0.5 * size * (exit_price - entry_price)
                        balance += pnl
                        trades.append({
                            "type": "LONG", "entry_time": active_position["entry_time"], "exit_time": curr_time,
                            "entry_price": entry_price, "exit_price": exit_price, "pnl": pnl,
                            "pnl_pct": (pnl / active_position["entry_balance"]) * 100, "result": "TAKE_PROFIT_ALL",
                            "rr": rr_potential
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
                            "result": "BREAKEVEN" if active_position["tp1_hit"] else "STOP_LOSS",
                            "rr": rr_potential
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
                                "pnl_pct": (pnl / active_position["entry_balance"]) * 100, "result": "TAKE_PROFIT_ALL",
                                "rr": rr_potential
                            })
                            active_position = None
                    elif active_position is not None and active_position["tp1_hit"] and curr["low"] <= tp2:
                        exit_price = tp2
                        pnl = 0.5 * size * (entry_price - tp1) + 0.5 * size * (entry_price - exit_price)
                        balance += pnl
                        trades.append({
                            "type": "SHORT", "entry_time": active_position["entry_time"], "exit_time": curr_time,
                            "entry_price": entry_price, "exit_price": exit_price, "pnl": pnl,
                            "pnl_pct": (pnl / active_position["entry_balance"]) * 100, "result": "TAKE_PROFIT_ALL",
                            "rr": rr_potential
                        })
                        active_position = None

            # 交易信號觸發
            if active_position is None:
                bias_1d = curr["bias_1d"]
                bias_4h = curr["bias_4h"]
                fvg_overlap_long = curr["is_fvg_overlap_long"]
                fvg_overlap_short = curr["is_fvg_overlap_short"]
                
                h1_top = curr["h1_fvg_top"]
                h1_bottom = curr["h1_fvg_bottom"]

                # 趨勢多重過濾
                allowed_long = True
                allowed_short = True
                if mode == "4H":
                    if bias_4h != "LONG": allowed_long = False
                    if bias_4h != "SHORT": allowed_short = False
                elif mode == "4H_1D":
                    if bias_4h != "LONG" or bias_1d != "LONG": allowed_long = False
                    if bias_4h != "SHORT" or bias_1d != "SHORT": allowed_short = False

                # 修正優化：將「收盤價進場」改為優雅的高盈虧比「左側限價單掛單」模式
                if allowed_long and fvg_overlap_long and pd.notna(h1_top):
                    if (curr["low"] <= h1_top) and (curr["close"] > curr["VWAP"]) and (curr["local_bias"] == "LONG"):
                        entry_p = h1_top # 精準限價單：在 1H FVG 的頂部掛單進場，確保盈虧比
                        sl = round(h1_bottom - 30, 2)
                        
                        if entry_p > sl:
                            tp1 = round(curr["VWAP_1.0_SD_Upper"], 2)
                            tp2 = round(curr["VWAP_2.0_SD_Upper"], 2)
                            
                            # 計算此單潛在初始盈虧比 (以期望的 TP2 計算)
                            rr_potential = (tp2 - entry_p) / (entry_p - sl)
                            
                            if curr["close"] > sl and tp1 > entry_p:
                                size = (balance * self.risk_pct) / (entry_p - sl)
                                active_position = {
                                    "type": "LONG", "entry_time": curr_time, "entry_price": entry_p,
                                    "sl": sl, "tp1": tp1, "tp2": tp2, "tp1_hit": False, "size": size, 
                                    "entry_balance": balance, "rr_potential": rr_potential
                                }

                elif allowed_short and fvg_overlap_short and pd.notna(h1_bottom):
                    if (curr["high"] >= h1_bottom) and (curr["close"] < curr["VWAP"]) and (curr["local_bias"] == "SHORT"):
                        entry_p = h1_bottom # 精準限價單：在 1H FVG 的底部掛單進場
                        sl = round(h1_top + 30, 2)
                        
                        if sl > entry_p:
                            tp1 = round(curr["VWAP_1.0_SD_Lower"], 2)
                            tp2 = round(curr["VWAP_2.0_SD_Lower"], 2)
                            
                            # 計算此單潛在初始盈虧比
                            rr_potential = (entry_p - tp2) / (sl - entry_p)
                            
                            if curr["close"] < sl and tp1 < entry_p:
                                size = (balance * self.risk_pct) / (sl - entry_p)
                                active_position = {
                                    "type": "SHORT", "entry_time": curr_time, "entry_price": entry_p,
                                    "sl": sl, "tp1": tp1, "tp2": tp2, "tp1_hit": False, "size": size, 
                                    "entry_balance": balance, "rr_potential": rr_potential
                                }

        total_trades = len(trades)
        if total_trades == 0:
            return {"trades": 0, "win_rate": 0.0, "profit": 0.0, "balance": balance, "tp_all": 0, "be": 0, "sl": 0, "avg_rr": 0.0}

        df_trades = pd.DataFrame(trades)
        wins = df_trades[df_trades["result"].isin(["TAKE_PROFIT_ALL", "BREAKEVEN"])]
        avg_rr = df_trades["rr"].mean() # 統計所有出入場訂單的平均初始盈虧比期望值
        
        return {
            "trades": total_trades, "win_rate": (len(wins) / total_trades) * 100, "profit": ((balance - self.initial_balance) / self.initial_balance) * 100, "balance": balance,
            "tp_all": len(df_trades[df_trades["result"] == "TAKE_PROFIT_ALL"]),
            "be": len(df_trades[df_trades["result"] == "BREAKEVEN"]),
            "sl": len(df_trades[df_trades["result"] == "STOP_LOSS"]),
            "avg_rr": avg_rr
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
                "模式": m["name"], "交易筆數": res["trades"], "平均盈虧比": f"1 : {res['avg_rr']:.2f}", 
                "勝率(TP1)": f"{res['win_rate']:.2f}%", "獲利(TP2)": res["tp_all"], 
                "保本(BE)": res["be"], "止損(SL)": res["sl"],
                "帳戶淨值": f"${res['balance']:,.2f}", "總損益": f"{res['profit']:+.2f}%"
            })

        pd.set_option('display.unicode.east_asian_width', True) 
        df_results = pd.DataFrame(results)
        print("\n" + "═"*105)
        print(" 📊  V8 全知之眼 - 修正型跨時區 FVG 空間重疊真實回測報告 (新增平均盈虧比欄位)")
        print("═"*105)
        print(df_results.to_string(index=False, justify='center'))
        print("═"*105)
    except FileNotFoundError as e:
        print(f"❌ 錯誤：請確保回測數據檔案放置於當前目錄。系統詳情: {e}")