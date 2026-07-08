import numpy as np
import pandas as pd
import gc

# ---------------------------------------------------------------------------
# V8 全知之眼 - 終極實盤對齊運算內核 (二次回踩防護對齊完美註解版 v9.8 - 右側追單爆發版)
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
        
        df_dt['bar_idx'] = df_dt.groupby('date').cumcount()
        
        vwap_deviation = self.df['close'] - self.df['VWAP']
        rolling_std = vwap_deviation.rolling(96, min_periods=1).std()
        rolling_std = np.where(df_dt['bar_idx'] < 16, np.nan, rolling_std)
        
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


def calculate_realtime_fvg(df, max_lifecycle_bars=192):
    df = df.copy()
    fvg_type = [None] * len(df)
    fvg_top = [np.nan] * len(df)
    fvg_bottom = [np.nan] * len(df)
    
    active_bullish_fvgs = []
    active_bearish_fvgs = []
    
    for i in range(2, len(df)):
        p_prev = df.iloc[i-2]
        p_next = df.iloc[i]
        
        if p_next['low'] > p_prev['high']:
            active_bullish_fvgs.append({'top': p_next['low'], 'bottom': p_prev['high'], 'created_at': i})
        elif p_next['high'] < p_prev['low']:
            active_bearish_fvgs.append({'top': p_prev['low'], 'bottom': p_next['high'], 'created_at': i})
            
        current_low = p_next['low']
        current_high = p_next['high']
        
        active_bullish_fvgs = [f for f in active_bullish_fvgs if current_low >= f['bottom'] and (i - f['created_at']) <= max_lifecycle_bars]
        active_bearish_fvgs = [f for f in active_bearish_fvgs if current_high <= f['top'] and (i - f['created_at']) <= max_lifecycle_bars]
        
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
    def __init__(self, initial_balance=10000.0, risk_pct=0.01, slippage_usd=15.0, entry_buffer_pct=0.0,
                 maker_fee=0.0002, taker_fee=0.0005, max_vol_pct=0.05, 
                 funding_rate_8h=0.0001, max_holding_bars=48, min_net_profit_r=1.2):
        self.initial_balance = initial_balance
        self.risk_pct = risk_pct
        self.slippage_usd = slippage_usd  
        self.entry_buffer_pct = entry_buffer_pct  
        self.maker_fee = maker_fee        
        self.taker_fee = taker_fee
        self.max_vol_pct = max_vol_pct          
        self.funding_rate_8h = funding_rate_8h  
        self.max_holding_bars = max_holding_bars  
        self.min_net_profit_r = min_net_profit_r  
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
                                     usecols=["datetime", "open", "high", "low"], chunksize=200000)
            m1_list = []
            for chunk in chunk_iter:
                chunk.index = pd.to_datetime(chunk.index).tz_localize(None)
                chunk = chunk.astype({"open": "float32", "high": "float32", "low": "float32"})
                m1_list.append(chunk)
                
            df_1m_all = pd.concat(m1_list).sort_index()
            df_1m_all['date_str'] = df_1m_all.index.date
            
            for date_key, group in df_1m_all.groupby('date_str'):
                self.m1_dict[date_key] = group[["open", "high", "low"]]
                
            print(f"💡 1m 數據快取完畢，共載入 {len(self.m1_dict)} 天的微觀歷史資料。")
            del df_1m_all, m1_list
            gc.collect()
        except FileNotFoundError:
            print("⚠️ 未檢測到 btc_1m.csv，系統將自動降級至保守高壓實盤模式。")

        print("正在注入大時區 V6 燃料扣抵...")
        for df in [self.df_1d, self.df_4h]:
            df["MA20"] = df["close"].rolling(20).mean()
            df["MA20_Ref"] = df["close"].shift(20)
            df["bias"] = np.where((df["close"] > df["MA20"]) & (df["close"] > df["MA20_Ref"]), "LONG", 
                                  np.where((df["close"] < df["MA20"]) & (df["close"] < df["MA20_Ref"]), "SHORT", "NONE"))

        print("正在計算機構失衡區 (FVG)...")
        df_1h_fvg = calculate_realtime_fvg(self.df_1h, max_lifecycle_bars=48)  
        df_15m_fvg = calculate_realtime_fvg(self.df_15m, max_lifecycle_bars=192) 
        
        print("正在建構 15m 全知指標矩陣...")
        self.v8_15m = V8_Omniscient_Eye(self.df_15m)
        df_res = self.v8_15m.df

        df_res["m15_fvg_type"] = df_15m_fvg["fvg_type"]
        df_res["m15_fvg_top"] = df_15m_fvg["fvg_top"]
        df_res["m15_fvg_bottom"] = df_15m_fvg["fvg_bottom"]

        df_1d_aligned = self.df_1d[["bias"]].copy()
        df_1d_aligned.index = df_1d_aligned.index + pd.Timedelta(days=1)
        df_4h_aligned = self.df_4h[["bias"]].copy()
        df_4h_aligned.index = df_4h_aligned.index + pd.Timedelta(hours=4)
        df_1h_fvg_aligned = df_1h_fvg.copy()
        df_1h_fvg_aligned.index = df_1h_fvg_aligned.index + pd.Timedelta(hours=1)

        print("正在執行多時區時間軸【嚴格實盤收盤對齊】...")
        df_res["bias_1d"] = df_1d_aligned["bias"].reindex(df_res.index, method="ffill")
        df_res["bias_4h"] = df_4h_aligned["bias"].reindex(df_res.index, method="ffill")
        
        df_res["h1_fvg_type"] = df_1h_fvg_aligned["fvg_type"].reindex(df_res.index, method="ffill")
        df_res["h1_fvg_top"] = df_1h_fvg_aligned["fvg_top"].reindex(df_res.index, method="ffill")
        df_res["h1_fvg_bottom"] = df_1h_fvg_aligned["fvg_bottom"].reindex(df_res.index, method="ffill")

        df_res["is_fvg_overlap_long"] = (df_res["m15_fvg_type"] == "BULLISH") & (df_res["h1_fvg_type"] == "BULLISH") & \
                                        ((df_res["m15_fvg_bottom"] <= df_res["h1_fvg_top"]) & (df_res["m15_fvg_top"] >= df_res["h1_fvg_bottom"]))
        df_res["is_fvg_overlap_short"] = (df_res["m15_fvg_type"] == "BEARISH") & (df_res["h1_fvg_type"] == "BEARISH") & \
                                         ((df_res["m15_fvg_top"] >= df_res["h1_fvg_bottom"]) & (df_res["m15_fvg_bottom"] <= df_res["h1_fvg_top"]))

        self.df_15m_indicators = df_res
        print("💡 V8 頂級交易員抗噪重疊引擎封裝完畢。")

    def _check_1m_sequence(self, start_time, end_time, target_a, target_b, a_is_low, b_is_high):
        date_key = start_time.date()
        if date_key not in self.m1_dict: return 'NONE'
        m1_slice = self.m1_dict[date_key].loc[start_time:end_time]
        if m1_slice.empty: return 'NONE'
        for _, row in m1_slice.iterrows():
            hit_a = (row['low'] <= target_a) if a_is_low else (row['high'] >= target_a)
            hit_b = (row['high'] >= target_b) if b_is_high else (row['low'] <= target_b)
            if hit_a and hit_b: return 'A' 
            if hit_a: return 'A'
            if hit_b: return 'B'
        return 'NONE'

    def run_backtest(self, mode="NONE", enable_be=False, tp1_close_pct=0.0, be_trigger_ratio=1.5,
                     enable_breakout_entry=True, breakout_min_rr=1.3):
        balance = self.initial_balance
        trades = []
        missed_trades_list = []  
        
        df = self.df_15m_indicators
        n_rows = len(df)
        active_position = None
        pending_retest_order = None  

        lookback = 96 

        for i in range(lookback, n_rows):
            prev = df.iloc[i-1]  
            curr = df.iloc[i]    
            curr_time = df.index[i]
            prev_time = df.index[i-1] 

            # 1. 持倉常規管理
            if active_position is not None:
                bars_held = i - active_position["entry_idx"]
                current_max_holding = self.max_holding_bars * 3 if active_position.get("be_active", False) else self.max_holding_bars
                
                if bars_held >= current_max_holding:
                    pos_type = active_position["type"]
                    acc_funding = active_position["accumulated_funding"]
                    size = active_position["size"]
                    pnl = (size * (curr["close"] - active_position["entry_price"])) if pos_type == "LONG" else (size * (active_position["entry_price"] - curr["close"]))
                    fee = (size * curr["close"]) * self.taker_fee
                    net_pnl = pnl - fee - acc_funding
                    balance += net_pnl
                    trades.append({"type": pos_type, "entry_time": active_position["entry_time"], "exit_time": curr_time, "pnl": net_pnl, "pnl_pct": (net_pnl / active_position["entry_balance"]) * 100, "result": "TIME_STOP", "rr_potential": active_position["rr_potential"], "rr_realized": net_pnl / active_position["actual_risk_usd"]})
                    active_position = None
                    continue

                if curr_time.hour % 8 == 0 and curr_time.minute == 0:
                    active_position["accumulated_funding"] += active_position["size"] * curr["open"] * self.funding_rate_8h

                pos_type = active_position["type"]
                entry_price = active_position["entry_price"]
                current_sl = active_position["sl"]
                tp1 = active_position["tp1"]
                tp2 = active_position["tp2"]
                size = active_position["size"]
                rr_potential = active_position["rr_potential"]
                actual_risk_usd = active_position["actual_risk_usd"]
                
                tp1_hit = active_position.get("tp1_hit", False)
                be_active = active_position.get("be_active", False)
                acc_funding = active_position["accumulated_funding"]

                be_trigger_p = entry_price + (tp1 - entry_price) * be_trigger_ratio if pos_type == "LONG" else entry_price - (entry_price - tp1) * be_trigger_ratio
                is_be_trigger_hit = (curr["high"] >= be_trigger_p) if pos_type == "LONG" else (curr["low"] <= be_trigger_p)
                if enable_be and is_be_trigger_hit and not be_active:
                    active_position["be_active"] = True
                    active_position["sl"] = entry_price 
                    current_sl = entry_price

                if pos_type == "LONG":
                    is_sl_hit = curr["low"] <= current_sl
                    is_tp1_hit_now = (not tp1_hit) and (curr["high"] >= tp1)
                    is_tp2_hit_now = curr["high"] >= tp2

                    if is_sl_hit and is_tp1_hit_now:
                        seq = self._check_1m_sequence(prev_time, curr_time, current_sl, tp1, a_is_low=True, b_is_high=True)
                        if seq == 'B': 
                            active_position["tp1_hit"] = True
                            if is_tp2_hit_now:
                                pnl = size * (tp1_close_pct * (tp1 - entry_price) + (1.0 - tp1_close_pct) * (tp2 - entry_price))
                                fee = (size * (tp1_close_pct * tp1 + (1.0 - tp1_close_pct) * tp2)) * self.maker_fee
                                balance += (pnl - fee - acc_funding)
                                trades.append({"type": "LONG", "entry_time": active_position["entry_time"], "exit_time": curr_time, "pnl": pnl - fee - acc_funding, "pnl_pct": ((pnl - fee - acc_funding) / active_position["entry_balance"]) * 100, "result": "TAKE_PROFIT_ALL", "rr_potential": rr_potential, "rr_realized": (pnl - fee - acc_funding) / actual_risk_usd})
                                active_position = None
                        else: 
                            pnl = size * (current_sl - entry_price) - (size * current_sl) * self.taker_fee - acc_funding
                            balance += pnl
                            trades.append({"type": "LONG", "entry_time": active_position["entry_time"], "exit_time": curr_time, "pnl": pnl, "pnl_pct": (pnl / active_position["entry_balance"]) * 100, "result": "BREAKEVEN" if be_active else "STOP_LOSS", "rr_potential": rr_potential, "rr_realized": pnl / actual_risk_usd})
                            active_position = None
                    elif is_sl_hit:
                        pnl = ((tp1_close_pct * size * (tp1 - entry_price) + (1.0 - tp1_close_pct) * size * (current_sl - entry_price)) if tp1_hit else size * (current_sl - entry_price)) - (size * current_sl) * self.taker_fee - acc_funding
                        balance += pnl
                        trades.append({"type": "LONG", "entry_time": active_position["entry_time"], "exit_time": curr_time, "pnl": pnl, "pnl_pct": (pnl / active_position["entry_balance"]) * 100, "result": "BREAKEVEN" if be_active else "STOP_LOSS", "rr_potential": rr_potential, "rr_realized": pnl / actual_risk_usd})
                        active_position = None
                    elif is_tp1_hit_now:
                        active_position["tp1_hit"] = True
                        if tp1_close_pct > 0: balance += (size * tp1_close_pct) * (tp1 - entry_price) - (size * tp1_close_pct * tp1) * self.maker_fee
                        if is_tp2_hit_now:
                            pnl = size * (tp1_close_pct * (tp1 - entry_price) + (1.0 - tp1_close_pct) * (tp2 - entry_price)) - (size * (tp1_close_pct * tp1 + (1.0 - tp1_close_pct) * tp2)) * self.maker_fee - acc_funding
                            balance += (pnl if tp1_close_pct == 0 else (size * (1.0 - tp1_close_pct) * (tp2 - entry_price) - (size * (1.0 - tp1_close_pct) * tp2) * self.maker_fee - acc_funding))
                            trades.append({"type": "LONG", "entry_time": active_position["entry_time"], "exit_time": curr_time, "pnl": pnl, "pnl_pct": (pnl / active_position["entry_balance"]) * 100, "result": "TAKE_PROFIT_ALL", "rr_potential": rr_potential, "rr_realized": pnl / actual_risk_usd})
                            active_position = None
                    elif active_position is not None and active_position.get("tp1_hit", False) and is_tp2_hit_now:
                        pnl = size * (tp1_close_pct * (tp1 - entry_price) + (1.0 - tp1_close_pct) * (tp2 - entry_price)) - (size * (tp1_close_pct * tp1 + (1.0 - tp1_close_pct) * tp2)) * self.maker_fee - acc_funding
                        balance += size * (1.0 - tp1_close_pct) * (tp2 - entry_price) - (size * (1.0 - tp1_close_pct) * tp2) * self.maker_fee - acc_funding
                        trades.append({"type": "LONG", "entry_time": active_position["entry_time"], "exit_time": curr_time, "pnl": pnl, "pnl_pct": (pnl / active_position["entry_balance"]) * 100, "result": "TAKE_PROFIT_ALL", "rr_potential": rr_potential, "rr_realized": pnl / actual_risk_usd})
                        active_position = None

                elif pos_type == "SHORT":
                    is_sl_hit = curr["high"] >= current_sl
                    is_tp1_hit_now = not tp1_hit and curr["low"] <= tp1
                    is_tp2_hit_now = curr["low"] <= tp2

                    if is_sl_hit and is_tp1_hit_now:
                        seq = self._check_1m_sequence(prev_time, curr_time, current_sl, tp1, a_is_low=False, b_is_high=True)
                        if seq == 'B': 
                            active_position["tp1_hit"] = True
                            if is_tp2_hit_now:
                                pnl = size * (tp1_close_pct * (entry_price - tp1) + (1.0 - tp1_close_pct) * (entry_price - tp2)) - (size * (tp1_close_pct * tp1 + (1.0 - tp1_close_pct) * tp2)) * self.maker_fee - acc_funding
                                balance += pnl
                                trades.append({"type": "SHORT", "entry_time": active_position["entry_time"], "exit_time": curr_time, "pnl": pnl, "pnl_pct": (pnl / active_position["entry_balance"]) * 100, "result": "TAKE_PROFIT_ALL", "rr_potential": rr_potential, "rr_realized": pnl / actual_risk_usd})
                                active_position = None
                        else: 
                            pnl = size * (entry_price - current_sl) - (size * current_sl) * self.taker_fee - acc_funding
                            balance += pnl
                            trades.append({"type": "SHORT", "entry_time": active_position["entry_time"], "exit_time": curr_time, "pnl": pnl, "pnl_pct": (pnl / active_position["entry_balance"]) * 100, "result": "BREAKEVEN" if be_active else "STOP_LOSS", "rr_potential": rr_potential, "rr_realized": pnl / actual_risk_usd})
                            active_position = None
                    elif is_sl_hit:
                        pnl = ((tp1_close_pct * size * (entry_price - tp1) + (1.0 - tp1_close_pct) * size * (entry_price - current_sl)) if tp1_hit else size * (entry_price - current_sl)) - (size * current_sl) * self.taker_fee - acc_funding
                        balance += pnl
                        trades.append({"type": "SHORT", "entry_time": active_position["entry_time"], "exit_time": curr_time, "pnl": pnl, "pnl_pct": (pnl / active_position["entry_balance"]) * 100, "result": "BREAKEVEN" if be_active else "STOP_LOSS", "rr_potential": rr_potential, "rr_realized": pnl / actual_risk_usd})
                        active_position = None
                    elif is_tp1_hit_now:
                        active_position["tp1_hit"] = True
                        if tp1_close_pct > 0: balance += (size * tp1_close_pct) * (entry_price - tp1) - (size * tp1_close_pct * tp1) * self.maker_fee
                        if is_tp2_hit_now:
                            pnl = size * (tp1_close_pct * (entry_price - tp1) + (1.0 - tp1_close_pct) * (entry_price - tp2)) - (size * (tp1_close_pct * tp1 + (1.0 - tp1_close_pct) * tp2)) * self.maker_fee - acc_funding
                            balance += (pnl if tp1_close_pct == 0 else (size * (1.0 - tp1_close_pct) * (entry_price - tp2) - (size * (1.0 - tp1_close_pct) * tp2) * self.maker_fee - acc_funding))
                            trades.append({"type": "SHORT", "entry_time": active_position["entry_time"], "exit_time": curr_time, "pnl": pnl, "pnl_pct": (pnl / active_position["entry_balance"]) * 100, "result": "TAKE_PROFIT_ALL", "rr_potential": rr_potential, "rr_realized": pnl / actual_risk_usd})
                            active_position = None
                    elif active_position is not None and active_position.get("tp1_hit", False) and is_tp2_hit_now:
                        pnl = size * (tp1_close_pct * (entry_price - tp1) + (1.0 - tp1_close_pct) * (entry_price - tp2)) - (size * (tp1_close_pct * tp1 + (1.0 - tp1_close_pct) * tp2)) * self.maker_fee - acc_funding
                        balance += size * (1.0 - tp1_close_pct) * (entry_price - tp2) - (size * (1.0 - tp1_close_pct) * tp2) * self.maker_fee - acc_funding
                        trades.append({"type": "SHORT", "entry_time": active_position["entry_time"], "exit_time": curr_time, "pnl": pnl, "pnl_pct": (pnl / active_position["entry_balance"]) * 100, "result": "TAKE_PROFIT_ALL", "rr_potential": rr_potential, "rr_realized": pnl / actual_risk_usd})
                        active_position = None

            # 2. 限價掛單池監控
            if active_position is None and pending_retest_order is not None:
                o_type = pending_retest_order["type"]
                limit_price = pending_retest_order["entry_price"]
                sl_p = pending_retest_order["sl"]

                if (i - pending_retest_order["created_idx"]) > 72:
                    pending_retest_order = None
                
                elif i > pending_retest_order["created_idx"]:
                    if o_type == "LONG":
                        if curr["low"] <= limit_price:
                            active_position = pending_retest_order
                            active_position["entry_idx"] = i
                            active_position["entry_time"] = curr_time
                            balance -= (active_position["size"] * limit_price) * self.maker_fee
                            pending_retest_order = None
                        # 🔧 修正點 1：拿掉觸及 tp1 取消掛單的潔癖限制，只留跌破止損的取消保護
                        elif curr["low"] <= sl_p:
                            pending_retest_order = None

                    elif o_type == "SHORT":
                        if curr["high"] >= limit_price:
                            active_position = pending_retest_order
                            active_position["entry_idx"] = i
                            active_position["entry_time"] = curr_time
                            balance -= (active_position["size"] * limit_price) * self.maker_fee
                            pending_retest_order = None
                        # 🔧 SHORT 同步修正
                        elif curr["high"] >= sl_p:
                            pending_retest_order = None

            # 3. 策略初次回踩雷達觸發 (Radar Trigger)
            if active_position is None and pending_retest_order is None:
                bias_1d = prev["bias_1d"]
                bias_4h = prev["bias_4h"]
                fvg_overlap_long = prev["is_fvg_overlap_long"]
                fvg_overlap_short = prev["is_fvg_overlap_short"]
                h1_top = prev["h1_fvg_top"]
                h1_bottom = prev["h1_fvg_bottom"]

                if pd.isna(prev["VWAP_SD"]): continue

                allowed_long, allowed_short = True, True
                if mode == "4H":
                    if bias_4h != "LONG": allowed_long = False
                    if bias_4h != "SHORT": allowed_short = False
                elif mode == "4H_1D":
                    if bias_4h != "LONG" or bias_1d != "LONG": allowed_long = False
                    if bias_4h != "SHORT" or bias_1d != "SHORT": allowed_short = False

                if allowed_long and fvg_overlap_long and pd.notna(h1_top) and pd.notna(h1_bottom):
                    if (prev["close"] > prev["VWAP"]) and (prev["local_bias"] == "LONG"):
                        fvg_height = h1_top - h1_bottom
                        limit_p = h1_top - (fvg_height * self.entry_buffer_pct)
                        vwap_sd_padding = max(prev["VWAP_SD"], 80.0)
                        
                        # 狀況 A：傳統左側限價回踩吃單
                        if curr["low"] <= limit_p:
                            real_entry_p = limit_p - self.slippage_usd
                            sl = round(real_entry_p - (vwap_sd_padding * 1.2), 2)
                            tp1 = round(prev["VWAP_1.0_SD_Upper"], 2)
                            tp2 = round(prev["VWAP_2.0_SD_Upper"] + vwap_sd_padding * 1.2, 2)
                            
                            expected_fee_drag = (limit_p * self.maker_fee) + (sl * self.taker_fee)
                            net_sl_dist = (real_entry_p - sl) + expected_fee_drag
                            
                            if net_sl_dist > 0 and tp2 > real_entry_p:
                                math_rr = ((tp1 - real_entry_p) * tp1_close_pct + (tp2 - real_entry_p) * (1.0 - tp1_close_pct)) / net_sl_dist
                                if math_rr >= self.min_net_profit_r:
                                    initial_risk_usd = balance * self.risk_pct
                                    size = min(initial_risk_usd / net_sl_dist, prev["volume"] * self.max_vol_pct)
                                    pending_retest_order = {
                                        "type": "LONG", "created_idx": i, "entry_price": limit_p,
                                        "sl": sl, "tp1": tp1, "tp2": tp2, "size": size, "entry_balance": balance,
                                        "rr_potential": math_rr, "actual_risk_usd": size * net_sl_dist,
                                        "tp1_hit": False, "be_active": False, "accumulated_funding": 0.0
                                    }
                        
                        # 🔧 修正點 2：狀況 B - 右側強勢突破直接追單機制
                        elif enable_breakout_entry and (curr["close"] > prev["high"]):
                            market_entry_p = curr["close"] + self.slippage_usd
                            sl = round(market_entry_p - (vwap_sd_padding * 1.2), 2)
                            tp1 = round(prev["VWAP_1.0_SD_Upper"], 2)
                            tp2 = round(prev["VWAP_2.0_SD_Upper"] + vwap_sd_padding * 1.2, 2)
                            
                            expected_fee_drag = (market_entry_p * self.taker_fee) + (sl * self.taker_fee)
                            net_sl_dist = (market_entry_p - sl) + expected_fee_drag
                            
                            if net_sl_dist > 0 and tp2 > market_entry_p:
                                math_rr = ((tp1 - market_entry_p) * tp1_close_pct + (tp2 - market_entry_p) * (1.0 - tp1_close_pct)) / net_sl_dist
                                # 檢查是否滿足右側追單最低盈虧比門檻
                                if math_rr >= breakout_min_rr:
                                    initial_risk_usd = balance * self.risk_pct
                                    size = min(initial_risk_usd / net_sl_dist, prev["volume"] * self.max_vol_pct)
                                    
                                    # 右側直接市價成交入局
                                    active_position = {
                                        "type": "LONG", "entry_idx": i, "entry_time": curr_time, "entry_price": market_entry_p,
                                        "sl": sl, "tp1": tp1, "tp2": tp2, "size": size, "entry_balance": balance,
                                        "rr_potential": math_rr, "actual_risk_usd": size * net_sl_dist,
                                        "tp1_hit": False, "be_active": False, "accumulated_funding": 0.0
                                    }
                                    balance -= (size * market_entry_p) * self.taker_fee
                        
                        elif curr["high"] >= round(prev["VWAP_1.0_SD_Upper"], 2):
                            missed_trades_list.append({"time": curr_time, "type": "LONG"})

                elif allowed_short and fvg_overlap_short and pd.notna(h1_bottom) and pd.notna(h1_top):
                    if (prev["close"] < prev["VWAP"]) and (prev["local_bias"] == "SHORT"):
                        fvg_height = h1_top - h1_bottom
                        limit_p = h1_bottom + (fvg_height * self.entry_buffer_pct)
                        vwap_sd_padding = max(prev["VWAP_SD"], 80.0)
                        
                        # 狀況 A：傳統左側限價回踩吃單
                        if curr["high"] >= limit_p:
                            real_entry_p = limit_p + self.slippage_usd
                            sl = round(real_entry_p + (vwap_sd_padding * 1.2), 2)
                            tp1 = round(prev["VWAP_1.0_SD_Lower"], 2)
                            tp2 = round(prev["VWAP_2.0_SD_Lower"] - vwap_sd_padding * 1.2, 2)
                            
                            expected_fee_drag = (limit_p * self.maker_fee) + (sl * self.taker_fee)
                            net_sl_dist = (sl - real_entry_p) + expected_fee_drag
                            
                            if net_sl_dist > 0 and real_entry_p > tp2:
                                math_rr = ((real_entry_p - tp1) * tp1_close_pct + (real_entry_p - tp2) * (1.0 - tp1_close_pct)) / net_sl_dist
                                if math_rr >= self.min_net_profit_r:
                                    initial_risk_usd = balance * self.risk_pct
                                    size = min(initial_risk_usd / net_sl_dist, prev["volume"] * self.max_vol_pct)
                                    pending_retest_order = {
                                        "type": "SHORT", "created_idx": i, "entry_price": limit_p,
                                        "sl": sl, "tp1": tp1, "tp2": tp2, "size": size, "entry_balance": balance,
                                        "rr_potential": math_rr, "actual_risk_usd": size * net_sl_dist,
                                        "tp1_hit": False, "be_active": False, "accumulated_funding": 0.0
                                    }
                        
                        # 🔧 修正點 3：SHORT 右側跌破追單機制
                        elif enable_breakout_entry and (curr["close"] < prev["low"]):
                            market_entry_p = curr["close"] - self.slippage_usd
                            sl = round(market_entry_p + (vwap_sd_padding * 1.2), 2)
                            tp1 = round(prev["VWAP_1.0_SD_Lower"], 2)
                            tp2 = round(prev["VWAP_2.0_SD_Lower"] - vwap_sd_padding * 1.2, 2)
                            
                            expected_fee_drag = (market_entry_p * self.taker_fee) + (sl * self.taker_fee)
                            net_sl_dist = (sl - market_entry_p) + expected_fee_drag
                            
                            if net_sl_dist > 0 and market_entry_p > tp2:
                                math_rr = ((market_entry_p - tp1) * tp1_close_pct + (market_entry_p - tp2) * (1.0 - tp1_close_pct)) / net_sl_dist
                                if math_rr >= breakout_min_rr:
                                    initial_risk_usd = balance * self.risk_pct
                                    size = min(initial_risk_usd / net_sl_dist, prev["volume"] * self.max_vol_pct)
                                    active_position = {
                                        "type": "SHORT", "entry_idx": i, "entry_time": curr_time, "entry_price": market_entry_p,
                                        "sl": sl, "tp1": tp1, "tp2": tp2, "size": size, "entry_balance": balance,
                                        "rr_potential": math_rr, "actual_risk_usd": size * net_sl_dist,
                                        "tp1_hit": False, "be_active": False, "accumulated_funding": 0.0
                                    }
                                    balance -= (size * market_entry_p) * self.taker_fee
                        
                        elif curr["low"] <= round(prev["VWAP_1.0_SD_Lower"], 2):
                            missed_trades_list.append({"time": curr_time, "type": "SHORT"})

        if active_position is not None:
            last_bar = df.iloc[-1]
            pnl = size * (last_bar["close"] - entry_price) if active_position["type"] == "LONG" else size * (entry_price - last_bar["close"])
            net_pnl = pnl - (size * last_bar["close"]) * self.taker_fee - active_position["accumulated_funding"]
            balance += net_pnl
            trades.append({"type": active_position["type"], "entry_time": active_position["entry_time"], "exit_time": df.index[-1], "pnl": net_pnl, "pnl_pct": (net_pnl / active_position["entry_balance"]) * 100, "result": "FORCE_CLOSE", "rr_potential": active_position["rr_potential"], "rr_realized": net_pnl / active_position["actual_risk_usd"]})

        return trades, missed_trades_list

    def analyze_results(self, trades):
        total_trades = len(trades)
        if total_trades == 0: return {"trades": 0, "win_rate": 0.0, "profit_pct": 0.0, "tp_all": 0, "be": 0, "sl": 0, "time_stop": 0, "avg_potential_rr": 0.0, "avg_realized_rr": 0.0}
        df_trades = pd.DataFrame(trades)
        wins = df_trades[df_trades["result"] == "TAKE_PROFIT_ALL"]
        avg_potential_rr = df_trades["rr_potential"].mean()
        df_profitable = df_trades[df_trades["rr_realized"] > 0]  
        df_losing = df_trades[df_trades["rr_realized"] < 0]      
        avg_win_r = df_profitable["rr_realized"].mean() if len(df_profitable) > 0 else 0.0
        avg_loss_r = abs(df_losing["rr_realized"].mean()) if len(df_losing) > 0 else 1.0
        return {
            "trades": total_trades, "win_rate": (len(wins) / total_trades) * 100, "profit_pct": df_trades["pnl_pct"].sum(),
            "tp_all": len(df_trades[df_trades["result"] == "TAKE_PROFIT_ALL"]) + len(df_trades[(df_trades["result"] == "FORCE_CLOSE") & (df_trades["pnl"] > 0)]),
            "be": len(df_trades[df_trades["result"] == "BREAKEVEN"]), "sl": len(df_trades[df_trades["result"] == "STOP_LOSS"]) + len(df_trades[(df_trades["result"] == "FORCE_CLOSE") & (df_trades["pnl"] <= 0)]),
            "time_stop": len(df_trades[df_trades["result"] == "TIME_STOP"]), "avg_potential_rr": avg_potential_rr, "avg_realized_rr": avg_win_r / avg_loss_r if avg_loss_r > 0 else 0.0
        }

    def generate_and_print_report(self, strategy_name, trades, missed_list):
        df_trades = pd.DataFrame(trades) if len(trades) > 0 else pd.DataFrame()
        df_missed = pd.DataFrame(missed_list) if len(missed_list) > 0 else pd.DataFrame(columns=["time", "type"])
        if not df_missed.empty: df_missed['month'] = df_missed['time'].dt.to_period('M')
        if not df_trades.empty: df_trades['month'] = df_trades['entry_time'].dt.to_period('M')
        all_months = sorted(list(set(([str(m) for m in df_trades['month'].unique()] if not df_trades.empty else []) + ([str(m) for m in df_missed['month'].unique()] if not df_missed.empty else []))))
        
        reports = []
        overall_res = self.analyze_results(trades)
        overall_m_rate = (len(df_missed) / (overall_res["trades"] + len(df_missed)) * 100) if (overall_res["trades"] + len(df_missed)) > 0 else 0.0
        reports.append({"PERIOD": "TOTAL", "TRADES": int(overall_res["trades"]), "P_RR": f"1:{overall_res['avg_potential_rr']:.2f}", "R_RR": f"1:{overall_res['avg_realized_rr']:.2f}", "WIN%": f"{overall_res['win_rate']:.2f}%", "TP2": int(overall_res["tp_all"]), "BE": int(overall_res["be"]), "TS": int(overall_res["time_stop"]), "SL": int(overall_res["sl"]), "PROFIT": f"{overall_res['profit_pct']:+.2f}%", "MISSED": len(df_missed), "M_RATE": f"{overall_m_rate:.1f}%"})
        
        for m_str in all_months:
            m_period = pd.Period(m_str, freq='M')
            m_trades_sub = df_trades[df_trades['month'] == m_period].to_dict('records') if not df_trades.empty else []
            m_missed_cnt = len(df_missed[df_missed['month'] == m_period]) if not df_missed.empty else 0
            m_res = self.analyze_results(m_trades_sub)
            m_rate_val = (m_missed_cnt / (m_res["trades"] + m_missed_cnt) * 100) if (m_res["trades"] + m_missed_cnt) > 0 else 0.0
            reports.append({"PERIOD": m_str, "TRADES": int(m_res["trades"]), "P_RR": f"1:{m_res['avg_potential_rr']:.2f}", "R_RR": f"1:{m_res['avg_realized_rr']:.2f}", "WIN%": f"{m_res['win_rate']:.2f}%", "TP2": int(m_res["tp_all"]), "BE": int(m_res["be"]), "TS": int(m_res["time_stop"]), "SL": int(m_res["sl"]), "PROFIT": f"{m_res['profit_pct']:+.2f}%", "MISSED": m_missed_cnt, "M_RATE": f"{m_rate_val:.1f}%"})
            
        def pad_cjk(text, width):
            text = str(text)
            cjk_count = sum(1 for char in text if ord(char) > 127)
            actual_pad = max(0, width - len(text) - cjk_count)
            return text + ' ' * actual_pad

        print("\n" + "="*125)
        print(f" V8 Omniscient Eye Report (二次回踩防護對齊版 v9.8) - {strategy_name}")
        print("="*125)
        header = f"{pad_cjk('PERIOD', 12)} | {'TRADES':<6} | {'P_RR':<8} | {'RE_RR':<8} | {'WIN%':<8} | {'TP2':<5} | {'BE':<5} | {'TS':<5} | {'SL':<5} | {'PROFIT':<9} | {'MISSED':<6} | {'M_RATE':<6}"
        print(header)
        print("-"*125)
        for r in reports:
            print(f"{pad_cjk(r['PERIOD'], 12)} | {r['TRADES']:<6} | {r['P_RR']:<8} | {r['R_RR']:<8} | {r['WIN%']:<8} | {r['TP2']:<5} | {r['BE']:<5} | {r['TS']:<5} | {r['SL']:<5} | {r['PROFIT']:<9} | {r['MISSED']:<6} | {r['M_RATE']:<6}")
        print("="*125 + "\n")


if __name__ == "__main__":
    try:
        backtester = MultiTimeframeBacktester(
            initial_balance=10000.0, 
            risk_pct=0.01,          
            slippage_usd=15.0,         
            entry_buffer_pct=0.50, # 放寬回踩深度門檻（20% 即觸發）   
            maker_fee=0.0002,         
            taker_fee=0.0005,        
            max_vol_pct=0.05,       
            funding_rate_8h=0.0001, 
            max_holding_bars=96,    
            min_net_profit_r=2.2 # 調降左側入場的基本盈虧比標準
        )
        
        cfg_be = False            
        cfg_tp1_pct = 0.0        
        cfg_be_trigger = 2.5     
        
        # 🔧 參數設定注入點：開啟右側突破追單，並給予 1.3 的彈性盈虧比限制
        trades_a, missed_a = backtester.run_backtest(
            mode="4H", 
            enable_be=cfg_be, 
            tp1_close_pct=cfg_tp1_pct, 
            be_trigger_ratio=cfg_be_trigger,
            enable_breakout_entry=True,  # 🔴 是否開啟突破追單
            breakout_min_rr=1.3          # 🔴 突破追單的最低盈虧比審查
        )
        backtester.generate_and_print_report("15m+1H+4H 右側雙追單爆發版 v9.8", trades_a, missed_a)
        
    except FileNotFoundError as e:
        print(f"❌ 錯誤: {e}")