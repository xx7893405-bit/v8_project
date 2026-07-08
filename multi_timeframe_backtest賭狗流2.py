import numpy as np
import pandas as pd
import gc

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
        
        # 1. 籌碼驗證：計算日內 VWAP
        cum_pv = df_dt.groupby('date')['pv'].cumsum()
        cum_v = df_dt.groupby('date')['volume'].cumsum()
        self.df['VWAP'] = cum_pv / cum_v
        
        # 🛠️ 陷阱修正 1：價格與 VWAP 價差的滾動標準差
        vwap_deviation = self.df['close'] - self.df['VWAP']
        rolling_std = vwap_deviation.rolling(96, min_periods=1).std()
        
        self.df['VWAP_SD'] = rolling_std
        self.df['VWAP_1.0_SD_Upper'] = self.df['VWAP'] + rolling_std
        self.df['VWAP_1.0_SD_Lower'] = self.df['VWAP'] - rolling_std
        self.df['VWAP_2.0_SD_Upper'] = self.df['VWAP'] + (rolling_std * 2.0)
        self.df['VWAP_2.0_SD_Lower'] = self.df['VWAP'] - (rolling_std * 2.0)
        
        # 2. V6 動能驗證（時間燃料）
        self.df['MA5'] = self.df['close'].rolling(5).mean()
        self.df['MA10'] = self.df['close'].rolling(10).mean()
        self.df['MA20'] = self.df['close'].rolling(20).mean()
        self.df['MA20_Ref'] = self.df['close'].shift(20)
        
        self.df['local_bias'] = np.where((self.df['close'] > self.df['MA20']) & (self.df['close'] > self.df['MA20_Ref']), "LONG",
                                         np.where((self.df['close'] < self.df['MA20']) & (self.df['close'] < self.df['MA20_Ref']), "SHORT", "NONE"))


def calculate_realtime_fvg(df, max_lifecycle_bars=192):
    """
    🛠️ 陷阱修正 3：防止老舊無效結構污染 (超過生命週期的 FVG 自動清理)
    """
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
            active_bullish_fvgs.append({'top': p_next['low'], 'bottom': p_prev['high'], 'created_at': i})
        elif p_next['high'] < p_prev['low']:
            active_bearish_fvgs.append({'top': p_prev['low'], 'bottom': p_next['high'], 'created_at': i})
            
        current_low = p_next['low']
        current_high = p_next['high']
        
        active_bullish_fvgs = [
            f for f in active_bullish_fvgs 
            if current_low >= f['bottom'] and (i - f['created_at']) <= max_lifecycle_bars
        ]
        active_bearish_fvgs = [
            f for f in active_bearish_fvgs 
            if current_high <= f['top'] and (i - f['created_at']) <= max_lifecycle_bars
        ]
        
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
        self.m1_dict = {} 
        self.load_all_data()

    def load_all_data(self):
        print("正在載入多時段歷史數據...")
        self.df_15m = pd.read_csv("btc_15m.csv", index_col="datetime", parse_dates=True).sort_index()
        self.df_1h = pd.read_csv("btc_1h.csv", index_col="datetime", parse_dates=True).sort_index()
        self.df_4h = pd.read_csv("btc_4h.csv", index_col="datetime", parse_dates=True).sort_index()
        self.df_1d = pd.read_csv("btc_1d.csv", index_col="datetime", parse_dates=True).sort_index()

        for df in [self.df_15m, self.df_1h, self.df_4h, self.df_1d]:
            df.index = pd.to_datetime(df.index).tz_localize(None)

        print("正在記憶體優化並分塊載入大檔案 btc_1m.csv...")
        try:
            chunk_iter = pd.read_csv("btc_1m.csv", index_col="datetime", parse_dates=True, 
                                     usecols=["datetime", "high", "low"], chunksize=200000)
            m1_list = []
            for chunk in chunk_iter:
                chunk.index = pd.to_datetime(chunk.index).tz_localize(None)
                chunk = chunk.astype({"high": "float32", "low": "float32"})
                m1_list.append(chunk)
                
            df_1m_all = pd.concat(m1_list).sort_index()
            df_1m_all['date_str'] = df_1m_all.index.date
            
            for date_key, group in df_1m_all.groupby('date_str'):
                self.m1_dict[date_key] = group[["high", "low"]]
                
            print(f"💡 1m 數據快取完畢，共載入 {len(self.m1_dict)} 天的微觀歷史資料。")
            del df_1m_all, m1_list
            gc.collect()
        except FileNotFoundError:
            print("⚠️ 未檢測到 btc_1m.csv，系統將全面自動降級至保守高壓實盤模式 (無 1m 數據時一律視為先掃止損)。")

        print("正在注入大時區 V6 燃料扣抵...")
        for df in [self.df_1d, self.df_4h]:
            df["MA20"] = df["close"].rolling(20).mean()
            df["MA20_Ref"] = df["close"].shift(20)
            df["bias"] = np.where((df["close"] > df["MA20"]) & (df["close"] > df["MA20_Ref"]), "LONG", 
                                  np.where((df["close"] < df["MA20"]) & (df["close"] < df["MA20_Ref"]), "SHORT", "NONE"))

        print("正在計算具有【動態緩解與生命週期過濾】的機構失衡區 (FVG)...")
        df_1h_fvg = calculate_realtime_fvg(self.df_1h, max_lifecycle_bars=48)  
        df_15m_fvg = calculate_realtime_fvg(self.df_15m, max_lifecycle_bars=192) 
        
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

    def _check_1m_sequence(self, start_time, end_time, target_a, target_b, a_is_low, b_is_high):
        date_key = start_time.date()
        if date_key not in self.m1_dict:
            return 'NODATA' 
        m1_slice = self.m1_dict[date_key].loc[start_time:end_time]
        if m1_slice.empty:
            return 'NODATA'
        for _, row in m1_slice.iterrows():
            hit_a = (row['low'] <= target_a) if a_is_low else (row['high'] >= target_a)
            hit_b = (row['high'] >= target_b) if b_is_high else (row['low'] <= target_b)
            if hit_a and hit_b: return 'A' 
            if hit_a: return 'A'
            if hit_b: return 'B'
        return 'NONE'

    def run_backtest(self, mode="NONE", enable_be=False, tp1_close_pct=0.0, be_trigger_ratio=1.0):
        balance = self.initial_balance
        trades = []
        missed_trades_count = 0  
        
        df = self.df_15m_indicators
        n_rows = len(df)
        active_position = None
        lookback = 96 

        for i in range(lookback, n_rows):
            prev = df.iloc[i-1]  
            curr = df.iloc[i]    
            curr_time = df.index[i]
            prev_time = df.index[i-1] 

            # 1. 持倉常規管理
            if active_position is not None:
                pos_type = active_position["type"]
                entry_price = active_position["entry_price"]
                current_sl = active_position["sl"]
                tp1 = active_position["tp1"]
                tp2 = active_position["tp2"]
                size = active_position["size"]
                rr_potential = active_position["rr_potential"]
                initial_risk_usd = active_position["initial_risk_usd"]
                tp1_hit = active_position["tp1_hit"]
                be_active = active_position["be_active"] 

                if pos_type == "LONG":
                    be_trigger_p = entry_price + (tp1 - entry_price) * be_trigger_ratio
                    is_be_trigger_hit = curr["high"] >= be_trigger_p if not be_active else False
                else:
                    be_trigger_p = entry_price - (entry_price - tp1) * be_trigger_ratio
                    is_be_trigger_hit = curr["low"] <= be_trigger_p if not be_active else False

                if enable_be and is_be_trigger_hit and not be_active:
                    active_position["be_active"] = True
                    active_position["sl"] = entry_price 
                    current_sl = entry_price

                if pos_type == "LONG":
                    is_sl_hit = curr["low"] <= current_sl
                    is_tp1_hit_now = not tp1_hit and curr["high"] >= tp1
                    is_tp2_hit_now = curr["high"] >= tp2

                    if is_sl_hit and is_tp1_hit_now:
                        seq = self._check_1m_sequence(prev_time, curr_time, current_sl, tp1, a_is_low=True, b_is_high=True)
                        if seq == 'NODATA': seq = 'A' 
                        
                        if seq == 'B': 
                            active_position["tp1_hit"] = True
                            if enable_be:
                                active_position["sl"] = entry_price
                                active_position["be_active"] = True
                                current_sl = entry_price
                            if is_tp2_hit_now:
                                pnl = size * (tp1_close_pct * (tp1 - entry_price) + (1.0 - tp1_close_pct) * (tp2 - entry_price))
                                balance += pnl
                                trades.append({
                                    "type": "LONG", "entry_time": active_position["entry_time"], "exit_time": curr_time,
                                    "pnl": pnl, "pnl_pct": (pnl / active_position["entry_balance"]) * 100, 
                                    "result": "TAKE_PROFIT_ALL", "rr_potential": rr_potential, "rr_realized": pnl / initial_risk_usd
                                })
                                active_position = None
                        else: 
                            pnl = size * (current_sl - entry_price)
                            balance += pnl
                            trades.append({
                                "type": "LONG", "entry_time": active_position["entry_time"], "exit_time": curr_time,
                                "pnl": pnl, "pnl_pct": (pnl / active_position["entry_balance"]) * 100, 
                                "result": "BREAKEVEN" if be_active else "STOP_LOSS", "rr_potential": rr_potential, "rr_realized": pnl / initial_risk_usd
                                })
                            active_position = None
                            
                    elif is_sl_hit:
                        pnl = ((tp1_close_pct * size * (tp1 - entry_price) + (1.0 - tp1_close_pct) * size * (current_sl - entry_price))
                               if tp1_hit else size * (current_sl - entry_price))
                        balance += pnl
                        res_tag = "BREAKEVEN" if (be_active or (tp1_hit and current_sl >= entry_price)) else "STOP_LOSS"
                        trades.append({
                            "type": "LONG", "entry_time": active_position["entry_time"], "exit_time": curr_time,
                            "pnl": pnl, "pnl_pct": (pnl / active_position["entry_balance"]) * 100, "result": res_tag, 
                            "rr_potential": rr_potential, "rr_realized": pnl / initial_risk_usd
                        })
                        active_position = None

                    elif is_tp1_hit_now:
                        active_position["tp1_hit"] = True
                        if enable_be:
                            active_position["sl"] = entry_price
                            active_position["be_active"] = True
                        if is_tp2_hit_now:
                            pnl = size * (tp1_close_pct * (tp1 - entry_price) + (1.0 - tp1_close_pct) * (tp2 - entry_price))
                            balance += pnl
                            trades.append({
                                "type": "LONG", "entry_time": active_position["entry_time"], "exit_time": curr_time,
                                "pnl": pnl, "pnl_pct": (pnl / active_position["entry_balance"]) * 100, "result": "TAKE_PROFIT_ALL", 
                                "rr_potential": rr_potential, "rr_realized": pnl / initial_risk_usd
                            })
                            active_position = None

                    elif active_position is not None and active_position["tp1_hit"] and is_tp2_hit_now:
                        pnl = tp1_close_pct * size * (tp1 - entry_price) + (1.0 - tp1_close_pct) * size * (tp2 - entry_price)
                        balance += pnl
                        trades.append({
                            "type": "LONG", "entry_time": active_position["entry_time"], "exit_time": curr_time,
                            "pnl": pnl, "pnl_pct": (pnl / active_position["entry_balance"]) * 100, "result": "TAKE_PROFIT_ALL", 
                            "rr_potential": rr_potential, "rr_realized": pnl / initial_risk_usd
                        })
                        active_position = None

                elif pos_type == "SHORT":
                    is_sl_hit = curr["high"] >= current_sl
                    is_tp1_hit_now = not tp1_hit and curr["low"] <= tp1
                    is_tp2_hit_now = curr["low"] <= tp2

                    if is_sl_hit and is_tp1_hit_now:
                        seq = self._check_1m_sequence(prev_time, curr_time, current_sl, tp1, a_is_low=False, b_is_high=False)
                        if seq == 'NODATA': seq = 'A'
                        
                        if seq == 'B': 
                            active_position["tp1_hit"] = True
                            if enable_be:
                                active_position["sl"] = entry_price
                                active_position["be_active"] = True
                                current_sl = entry_price
                            if is_tp2_hit_now:
                                pnl = size * (tp1_close_pct * (entry_price - tp1) + (1.0 - tp1_close_pct) * (entry_price - tp2))
                                balance += pnl
                                trades.append({
                                    "type": "SHORT", "entry_time": active_position["entry_time"], "exit_time": curr_time,
                                    "pnl": pnl, "pnl_pct": (pnl / active_position["entry_balance"]) * 100, "result": "TAKE_PROFIT_ALL", 
                                    "rr_potential": rr_potential, "rr_realized": pnl / initial_risk_usd
                                })
                                active_position = None
                        else: 
                            pnl = size * (entry_price - current_sl)
                            balance += pnl
                            trades.append({
                                "type": "SHORT", "entry_time": active_position["entry_time"], "exit_time": curr_time,
                                "pnl": pnl, "pnl_pct": (pnl / active_position["entry_balance"]) * 100, 
                                "result": "BREAKEVEN" if be_active else "STOP_LOSS", "rr_potential": rr_potential, "rr_realized": pnl / initial_risk_usd
                            })
                            active_position = None
                    elif is_sl_hit:
                        pnl = ((tp1_close_pct * size * (entry_price - tp1) + (1.0 - tp1_close_pct) * size * (entry_price - current_sl))
                               if tp1_hit else size * (entry_price - current_sl))
                        balance += pnl
                        res_tag = "BREAKEVEN" if (be_active or (tp1_hit and current_sl <= entry_price)) else "STOP_LOSS"
                        trades.append({
                            "type": "SHORT", "entry_time": active_position["entry_time"], "exit_time": curr_time,
                            "pnl": pnl, "pnl_pct": (pnl / active_position["entry_balance"]) * 100, "result": res_tag, 
                            "rr_potential": rr_potential, "rr_realized": pnl / initial_risk_usd
                        })
                        active_position = None

                    elif is_tp1_hit_now:
                        active_position["tp1_hit"] = True
                        if enable_be:
                            active_position["sl"] = entry_price
                            active_position["be_active"] = True
                        if is_tp2_hit_now:
                            pnl = size * (tp1_close_pct * (entry_price - tp1) + (1.0 - tp1_close_pct) * (entry_price - tp2))
                            balance += pnl
                            trades.append({
                                "type": "SHORT", "entry_time": active_position["entry_time"], "exit_time": curr_time,
                                "pnl": pnl, "pnl_pct": (pnl / active_position["entry_balance"]) * 100, "result": "TAKE_PROFIT_ALL", 
                                "rr_potential": rr_potential, "rr_realized": pnl / initial_risk_usd
                            })
                            active_position = None

                    elif active_position is not None and active_position["tp1_hit"] and is_tp2_hit_now:
                        pnl = tp1_close_pct * size * (entry_price - tp1) + (1.0 - tp1_close_pct) * size * (entry_price - tp2)
                        balance += pnl
                        trades.append({
                            "type": "SHORT", "entry_time": active_position["entry_time"], "exit_time": curr_time,
                            "pnl": pnl, "pnl_pct": (pnl / active_position["entry_balance"]) * 100, "result": "TAKE_PROFIT_ALL", 
                            "rr_potential": rr_potential, "rr_realized": pnl / initial_risk_usd
                        })
                        active_position = None

            # 2. 交易信號觸發 (完全不保本：不推保本、不減倉，直接拼 TP2 與滿額 SL)
            if active_position is None:
                bias_1d = prev["bias_1d"]
                bias_4h = prev["bias_4h"]
                fvg_overlap_long = prev["is_fvg_overlap_long"]
                fvg_overlap_short = prev["is_fvg_overlap_short"]
                h1_top = prev["h1_fvg_top"]
                h1_bottom = prev["h1_fvg_bottom"]

                allowed_long, allowed_short = True, True
                if mode == "4H":
                    if bias_4h != "LONG": allowed_long = False
                    if bias_4h != "SHORT": allowed_short = False
                elif mode == "4H_1D":
                    if bias_4h != "LONG" or bias_1d != "LONG": allowed_long = False
                    if bias_4h != "SHORT" or bias_1d != "SHORT": allowed_short = False

                # 🟢 多頭進場
                if allowed_long and fvg_overlap_long and pd.notna(h1_top):
                    if (prev["close"] > prev["VWAP"]) and (prev["local_bias"] == "LONG"):
                        entry_p = h1_top
                        sl = round(h1_bottom - 30, 2)
                        tp1 = round(prev["VWAP_1.0_SD_Upper"], 2)
                        
                        if curr["low"] <= entry_p and prev["close"] > sl and tp1 > entry_p:
                            tp2 = round(prev["VWAP_2.0_SD_Upper"], 2)
                            rr_potential = (tp2 - entry_p) / (entry_p - sl)
                            initial_risk_usd = balance * self.risk_pct
                            size = initial_risk_usd / (entry_p - sl)
                            
                            if curr["low"] <= sl:
                                pnl = -initial_risk_usd
                                balance += pnl
                                trades.append({
                                    "type": "LONG", "entry_time": curr_time, "exit_time": curr_time,
                                    "pnl": pnl, "pnl_pct": (pnl / balance) * 100, "result": "STOP_LOSS",
                                    "rr_potential": rr_potential, "rr_realized": -1.0
                                })
                            else:
                                active_position = {
                                    "type": "LONG", "entry_time": curr_time, "entry_price": entry_p,
                                    "original_sl": sl, "sl": sl, "tp1": tp1, "tp2": tp2, "tp1_hit": False, 
                                    "be_active": False, "size": size, "entry_balance": balance, 
                                    "rr_potential": rr_potential, "initial_risk_usd": initial_risk_usd
                                }
                        elif curr["low"] > entry_p and curr["high"] >= tp1:
                            missed_trades_count += 1

                # 🔴 空頭進場
                elif allowed_short and fvg_overlap_short and pd.notna(h1_bottom):
                    if (prev["close"] < prev["VWAP"]) and (prev["local_bias"] == "SHORT"):
                        entry_p = h1_bottom
                        sl = round(h1_top + 30, 2)
                        tp1 = round(prev["VWAP_1.0_SD_Lower"], 2)
                        
                        if curr["high"] >= entry_p and prev["close"] < sl and tp1 < entry_p:
                            py2 = round(prev["VWAP_2.0_SD_Lower"], 2)
                            rr_potential = (entry_p - py2) / (sl - entry_p)
                            initial_risk_usd = balance * self.risk_pct
                            size = initial_risk_usd / (sl - entry_p)
                            
                            if curr["high"] >= sl:
                                pnl = -initial_risk_usd
                                balance += pnl
                                trades.append({
                                    "type": "SHORT", "entry_time": curr_time, "exit_time": curr_time,
                                    "pnl": pnl, "pnl_pct": (pnl / balance) * 100, "result": "STOP_LOSS",
                                    "rr_potential": rr_potential, "rr_realized": -1.0
                                })
                            else:
                                active_position = {
                                    "type": "SHORT", "entry_time": curr_time, "entry_price": entry_p,
                                    "original_sl": sl, "sl": sl, "tp1": tp1, "tp2": py2, "tp1_hit": False, 
                                    "be_active": False, "size": size, "entry_balance": balance, 
                                    "rr_potential": rr_potential, "initial_risk_usd": initial_risk_usd
                                }
                        elif curr["high"] < entry_p and curr["low"] <= tp1:
                            missed_trades_count += 1

        return trades, missed_trades_count

    def analyze_results(self, trades):
        total_trades = len(trades)
        if total_trades == 0:
            return {"trades": 0, "win_rate": 0.0, "profit_pct": 0.0, "tp_all": 0, "be": 0, "sl": 0, "avg_potential_rr": 0.0, "avg_realized_rr": 0.0}

        df_trades = pd.DataFrame(trades)
        wins = df_trades[df_trades["pnl"] >= 0] 
        avg_potential_rr = df_trades["rr_potential"].mean()
        
        df_profitable = df_trades[df_trades["pnl"] > 0]  
        df_losing = df_trades[df_trades["pnl"] < 0]      
        
        avg_win_return = df_profitable["rr_realized"].mean() if len(df_profitable) > 0 else 0
        avg_loss_cost = abs(df_losing["rr_realized"].mean()) if len(df_losing) > 0 else 1
        pure_realized_rr = avg_win_return / avg_loss_cost if avg_loss_cost > 0 else avg_win_return
        
        total_profit_pct = df_trades["pnl_pct"].sum() 
        
        return {
            "trades": total_trades, 
            "win_rate": (len(wins) / total_trades) * 100, 
            "profit_pct": total_profit_pct,
            "tp_all": len(df_trades[df_trades["result"] == "TAKE_PROFIT_ALL"]),
            "be": len(df_trades[df_trades["result"] == "BREAKEVEN"]),
            "sl": len(df_trades[df_trades["result"] == "STOP_LOSS"]),
            "avg_potential_rr": avg_potential_rr,
            "avg_realized_rr": pure_realized_rr
        }

    def generate_and_print_report(self, strategy_name, trades, missed_count):
        if len(trades) == 0:
            print(f"❌ 策略【{strategy_name}】未觸發任何有效交易。")
            return
            
        df_all = pd.DataFrame(trades)
        df_all['month'] = df_all['entry_time'].dt.to_period('M')
        
        reports = []
        
        # 1. 注入總計歷史欄位 (完全對齊之前總紀錄格式欄位)
        overall = self.analyze_results(trades)
        reports.append({
            "時間區段": "🔥 全年歷史總計", "實質交易": overall["trades"],
            "預期盈虧比": f"1 : {overall['avg_potential_rr']:.2f}", "實質純賺賠比": f"1 : {overall['avg_realized_rr']:.2f}",
            "勝率(正報酬)": f"{overall['win_rate']:.2f}%", "吃滿(TP2)": overall["tp_all"], 
            "保本(BE)": overall["be"], "滿額止損(SL)": overall["sl"], "階段損益": f"{overall['profit_pct']:+.2f}%"
        })
        
        # 2. 注入每月碎裂化明細
        for month, group in df_all.groupby('month'):
            m_trades = group.to_dict('records')
            m_res = self.analyze_results(m_trades)
            reports.append({
                "時間區段": f"📅 {month}", "實質交易": m_res["trades"],
                "預期盈虧比": f"1 : {m_res['avg_potential_rr']:.2f}", "實質純賺賠比": f"1 : {m_res['avg_realized_rr']:.2f}",
                "勝率(正報酬)": f"{m_res['win_rate']:.2f}%", "吃滿(TP2)": m_res["tp_all"], 
                "保本(BE)": m_res["be"], "滿額止損(SL)": m_res["sl"], "階段損益": f"{m_res['profit_pct']:+.2f}%"
            })
            
        df_report = pd.DataFrame(reports)
        print("\n" + "═"*145)
        print(f" 📊  V8 全知之眼 - 策略：【{strategy_name}】跨月碎裂化戰報")
        print("═"*145)
        print(df_report.to_string(index=False, justify='center'))
        print("═"*145)


if __name__ == "__main__":
    try:
        backtester = MultiTimeframeBacktester()
        
        # 核心策略 A: 15m+1H 基礎版 (完全不保本)
        trades_a, missed_a = backtester.run_backtest(mode="NONE", enable_be=False, tp1_close_pct=0.0)
        backtester.generate_and_print_report("15m+1H 基礎版 (完全不保本)", trades_a, missed_a)
        
        # 核心策略 B: 15m+1H+4H 三重共振 (完全不保本)
        trades_b, missed_b = backtester.run_backtest(mode="4H", enable_be=False, tp1_close_pct=0.0)
        backtester.generate_and_print_report("15m+1H+4H 三重共振 (完全不保本)", trades_b, missed_b)
        
    except FileNotFoundError as e:
        print(f"❌ 錯誤：請確保回測數據檔案放置於當前目錄。系統詳情: {e}")