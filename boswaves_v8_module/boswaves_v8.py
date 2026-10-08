"""隔離的 BOSWaves 1h 研究引擎（候選移植，不宣稱 Pine 逐筆相同）。

設計不觸碰既有 V8 策略/引擎。進場：確認 1h Flip 時收盤價，
SL 與 T1~T4 由 Flip 當下固定 ATR 決定。A: 初始 SL/Flip 出場；
C: T2→0R, T3→+1R, T4→+2R，只在後續 1m 才啟用保護。

原始 Pine 與實際 TV A/C 策略原碼尚未取得。stop_reference_mode='flip_extremes'
依第三方原碼拆解與目前交易 CSV 的特徵建立候選，正式同等性需用 9~10 月逐筆對帳確認。
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional
import math

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Params:
    alma_length: int = 34
    alma_offset: float = 0.85
    alma_sigma: float = 6.0
    deviation_length: int = 34
    trend_confirmation: float = 0.65
    slope_length: int = 3
    minimum_slope: float = 0.08
    atr_length: int = 14
    stop_structure_lookback: int = 12
    minimum_stop_atr: float = 0.75
    maximum_stop_atr: float = 3.0
    stop_reference_mode: str = "flip_extremes"  # 候選：同方向 Flip 極值歷史
    flip_history_full_window: bool = False  # 原碼細節待 TradingView 對帳確認
    fee_per_side: float = 0.0005
    entry_slippage_usd: float = 0.0
    stop_slippage_usd: float = 0.0
    flip_slippage_usd: float = 0.0
    risk_fraction: float = 0.03
    max_leverage: float = 20.0
    initial_equity: float = 10000.0

    def validate(self) -> None:
        if any(x < 2 for x in (self.alma_length, self.deviation_length, self.atr_length)):
            raise ValueError("ALMA / deviation / ATR lengths must be >= 2")
        if self.slope_length < 1 or self.stop_structure_lookback < 1:
            raise ValueError("slope_length and stop_structure_lookback must be positive")
        if not (0 <= self.alma_offset <= 1 and self.alma_sigma > 0):
            raise ValueError("invalid ALMA offset or sigma")
        if not (0 < self.minimum_stop_atr <= self.maximum_stop_atr):
            raise ValueError("stop ATR range must be ascending positive")
        if self.stop_reference_mode not in ("flip_extremes", "rolling_bars"):
            raise ValueError("stop_reference_mode must be flip_extremes or rolling_bars")
        if self.risk_fraction <= 0 or self.max_leverage <= 0 or self.initial_equity <= 0:
            raise ValueError("risk/leverage/equity must be positive")
        if min(self.fee_per_side, self.entry_slippage_usd, self.stop_slippage_usd, self.flip_slippage_usd) < 0:
            raise ValueError("cost inputs must be nonnegative")


def validate_ohlcv(df: pd.DataFrame, freq: str = "1min", require_contiguous: bool = True) -> pd.DataFrame:
    if df.empty:
        raise ValueError("empty market data")
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("market data requires DatetimeIndex of UTC open times")
    if df.index.tz is None:
        raise ValueError("index must have explicit UTC timezone")
    if str(df.index.tz) != "UTC":
        df = df.tz_convert("UTC")
    if not df.index.is_monotonic_increasing or df.index.has_duplicates:
        raise ValueError("duplicate/unsorted candles")
    for col in ("open", "high", "low", "close"):
        if col not in df.columns:
            raise ValueError(f"missing {col}")
        if not np.isfinite(df[col].to_numpy(dtype=float)).all() or (df[col] <= 0).any():
            raise ValueError(f"invalid {col}")
    if ((df.high < df[["open", "close", "low"]].max(axis=1)) |
            (df.low > df[["open", "close", "high"]].min(axis=1))).any():
        raise ValueError("invalid candle high/low")
    if require_contiguous and len(df)>1 and (df.index.to_series().diff().iloc[1:] != pd.Timedelta(freq)).any():
        raise ValueError("missing candles: fail closed rather than forward fill")
    return df


def hourly_from_1m(m1: pd.DataFrame) -> pd.DataFrame:
    validate_ohlcv(m1)
    if m1.index[0].minute != 0 or len(m1) % 60 or m1.index[-1].minute != 59:
        raise ValueError("only complete UTC 1h candles can be resampled; supply full-minute aligned span")
    return m1.resample("1h", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last"
    })


def _alma(prices: pd.Series, p: Params) -> pd.Series:
    n = p.alma_length
    mu = p.alma_offset * (n - 1)
    s = n / p.alma_sigma
    i = np.arange(n, dtype=float)
    weights = np.exp(-((i-mu) ** 2) / (2*s*s))
    weights /= weights.sum()
    values = prices.to_numpy(dtype=float)
    result = np.full(len(values), np.nan)
    if len(values) >= n:
        result[n-1:] = np.convolve(values, weights[::-1], mode="valid")
    return pd.Series(result, index=prices.index, name="alma")


def _pine_atr(ohlc: pd.DataFrame, length: int) -> pd.Series:
    """Wilder RMA true range with initial SMA seed (Pine ta.atr convention)."""
    prev = ohlc.close.shift()
    tr = pd.concat([ohlc.high-ohlc.low, (ohlc.high-prev).abs(), (ohlc.low-prev).abs()], axis=1).max(axis=1)
    vals = tr.to_numpy(dtype=float)
    res = np.full(len(vals), np.nan)
    if len(vals) >= length:
        res[length-1] = vals[:length].mean()
        for i in range(length, len(vals)):
            res[i] = (res[i-1]*(length-1)+vals[i]) / length
    return pd.Series(res, index=ohlc.index, name="atr")


def indicators(hourly: pd.DataFrame, p: Params) -> pd.DataFrame:
    p.validate()
    validate_ohlcv(hourly, freq="1h")
    f = hourly[["open", "high", "low", "close"]].copy()
    f["alma"] = _alma(f.close, p)
    f["atr"] = _pine_atr(f, p.atr_length)
    f["deviation"] = f.close.rolling(p.deviation_length, min_periods=p.deviation_length).std(ddof=0)
    f["slope_atr"] = (f.alma-f.alma.shift(p.slope_length))/f.atr
    f["upper"] = f.alma + p.trend_confirmation*f.deviation
    f["lower"] = f.alma - p.trend_confirmation*f.deviation
    f["long_condition"] = (f.close > f.upper) & (f.slope_atr > p.minimum_slope)
    f["short_condition"] = (f.close < f.lower) & (f.slope_atr < -p.minimum_slope)
    state = 0
    events = np.zeros(len(f), dtype=np.int8)
    for i, (long_cond, short_cond) in enumerate(zip(f.long_condition.to_numpy(),f.short_condition.to_numpy())):
        if long_cond and state != 1:
            state, events[i] = 1, 1
        elif short_cond and state != -1:
            state, events[i] = -1, -1
    f["flip"] = events
    return f


def make_flip_plans(hourly: pd.DataFrame, p: Params) -> pd.DataFrame:
    f = indicators(hourly, p)
    long_flip_lows: list[float] = []
    short_flip_highs: list[float] = []
    plans = []
    for idx, bar in f.iterrows():
        side = int(bar.flip)
        if not side:
            continue
        if p.stop_reference_mode == "rolling_bars":
            # 對帳用途；是否含當前 Flip 根由 TV 原始碼確認。
            segment = f.loc[:idx].tail(p.stop_structure_lookback)
            ref = float(segment.low.min() if side == 1 else segment.high.max())
        else:
            if side == 1:
                long_flip_lows.append(float(bar.low))
                available = long_flip_lows
                values = long_flip_lows[-p.stop_structure_lookback:]
                ref = min(values) if values and (not p.flip_history_full_window or len(available) >= p.stop_structure_lookback) else math.nan
            else:
                short_flip_highs.append(float(bar.high))
                available = short_flip_highs
                values = short_flip_highs[-p.stop_structure_lookback:]
                ref = max(values) if values and (not p.flip_history_full_window or len(available) >= p.stop_structure_lookback) else math.nan
        entry = float(bar.close)
        raw_risk = side*(entry-ref) if math.isfinite(ref) else math.nan
        if not math.isfinite(raw_risk):
            risk = p.minimum_stop_atr*float(bar.atr)
            bound = "missing_reference"
        else:
            risk = min(max(raw_risk, p.minimum_stop_atr*bar.atr), p.maximum_stop_atr*bar.atr)
            bound = "max" if raw_risk>p.maximum_stop_atr*bar.atr else ("min" if raw_risk<p.minimum_stop_atr*bar.atr else "structure")
        plans.append(dict(
            signal_open_time=idx, signal_close_time=idx+pd.Timedelta(hours=1),
            side="LONG" if side==1 else "SHORT", sign=side,
            entry_price=entry, atr=float(bar.atr),
            raw_structure_sl=ref, raw_risk_atr=raw_risk/float(bar.atr) if math.isfinite(raw_risk) else math.nan,
            initial_sl=entry-side*risk, initial_risk=risk, risk_atr=risk/float(bar.atr), stop_bound=bound,
        ))
    if not plans:
        return pd.DataFrame(columns=["signal_open_time", "signal_close_time", "side", "sign", "entry_price", "atr", "raw_structure_sl", "raw_risk_atr", "initial_sl", "initial_risk", "risk_atr", "stop_bound"])
    return pd.DataFrame(plans)


def _adverse_stop_hit(sign: int, low: float, high: float, sl: float) -> bool:
    return (low <= sl) if sign == 1 else (high >= sl)


def _realized_record(pos: dict, timestamp, price: float, reason: str, fee: float, slip: float) -> dict:
    raw_risk = float(pos["initial_risk"])
    sign = int(pos["sign"])
    entry = float(pos["entry_price"])
    gross_r = sign*(price-entry)/raw_risk
    cost_r = ((entry+price)*fee + float(pos["entry_slippage_usd"])+slip)/raw_risk
    out = {k: v for k,v in pos.items() if not k.startswith("_")}
    out.update(exit_time=timestamp, exit_price=float(price), exit_reason=reason,
        gross_r=gross_r, cost_r=cost_r, realized_r=gross_r-cost_r,
        highest_reached_r=pos["_max_fav_r"], maximum_adverse_r=pos["_max_adv_r"],
        max_target_hit=min(4,int(math.floor(max(0,pos["_max_fav_r"])))),
        final_protected_r=pos["_stop_stage"],
        quantity=float(pos["_quantity"]), gross_usdt=float(pos["_quantity"]*gross_r*raw_risk),
        cost_usdt=float(pos["_quantity"]*cost_r*raw_risk),
        net_usdt=float(pos["_quantity"]*(gross_r-cost_r)*raw_risk),
        duration_hours=float((timestamp-pos["entry_time"]).total_seconds()/3600.0),
    )
    return out


def run_version(hourly: pd.DataFrame, minute: pd.DataFrame, plans: pd.DataFrame, p: Params,
                version: str, warmup_cutoff: Optional[pd.Timestamp]=None) -> pd.DataFrame:
    """按真實 UTC 時序：分鐘內先測舊保護 SL、再在分鐘結束更新里程碑；1h 收盤才翻轉進場。

    同分鐘觸發新 T 與原 SL 時按保守順序（原 SL 優先）。有 1m 微觀順序仍無 tick，結果需揭露。
    """
    if version not in ("A", "C"):
        raise ValueError("only A/C versions supported")
    validate_ohlcv(minute)
    # 也允許 slice 1m，剛好涵蓋完整 1h 集合
    if not hourly.index.equals(hourly_from_1m(minute).index):
        raise ValueError("hourly/minute time alignment mismatch")
    if len(plans) and plans.signal_close_time.duplicated().any():
        raise ValueError("duplicate Flip signal")
    events = {row.signal_close_time: row._asdict() for row in plans.itertuples(index=False)}
    minutes = minute[["open","high","low","close"]].to_numpy(dtype=float)
    mtimes = minute.index
    out = []
    pos: dict | None = None
    balance = float(p.initial_equity)
    trade_id = 0
    for j in range(len(minute)):
        t=mtimes[j]
        mopen,mhigh,mlow,mclose = minutes[j]
        if pos is not None:
            sign=int(pos["sign"])
            stop=float(pos["_stop"])
            if _adverse_stop_hit(sign,mlow,mhigh,stop):
                # 1m gap-through 使用開盤價的較不利價（不虛構 limit stop 成交）
                fill = min(mopen,stop) if sign==1 else max(mopen,stop)
                why="Initial SL" if pos["_stop_stage"] == -1 else f"Protect {pos['_stop_stage']}R"
                rec=_realized_record(pos,t,fill,why,p.fee_per_side,p.stop_slippage_usd)
                if warmup_cutoff is None or rec["entry_time"]>=warmup_cutoff:
                    out.append(rec)
                balance += rec["net_usdt"]
                rec["equity_after_exit"]=balance
                pos=None
            else:
                fav = sign*((mhigh if sign==1 else mlow)-pos["entry_price"])/pos["initial_risk"]
                adv = -sign*((mlow if sign==1 else mhigh)-pos["entry_price"])/pos["initial_risk"]
                pos["_max_fav_r"] = max(pos["_max_fav_r"],fav)
                pos["_max_adv_r"] = max(pos["_max_adv_r"],adv)
                if version == "C":
                    # 只在本分鐘完成後開始保護下一根分鐘 K
                    # 里程碑>=2/3/4，分別保護0/1/2R。當分鐘最高觸及檢視區間的結果不做同分鐘套利。
                    newstage = min(2, int(math.floor(pos["_max_fav_r"]))-2)
                    if newstage >= 0 and newstage > pos["_stop_stage"]:
                        pos["_stop_stage"] = newstage
                        pos["_stop"] = pos["entry_price"]+sign*newstage*pos["initial_risk"]
        # 1h bar interval is [HH:00,HH:59], Flip at HH+1h close
        end=t+pd.Timedelta(minutes=1)
        event=events.get(end)
        if event is not None:
            if pos is not None:
                rec=_realized_record(pos,end,float(mclose),"Flip " + event["side"],p.fee_per_side,p.flip_slippage_usd)
                if warmup_cutoff is None or rec["entry_time"]>=warmup_cutoff:
                    out.append(rec)
                balance += rec["net_usdt"]
                rec["equity_after_exit"]=balance
                pos=None
            trade_id+=1
            erisk=float(event["initial_risk"])
            entry=float(event["entry_price"])
            qty=min(max(balance,0)*p.risk_fraction/erisk, max(balance,0)*p.max_leverage/entry)
            pos=dict(event, trade_id=trade_id, version=version, entry_time=end,
                entry_slippage_usd=p.entry_slippage_usd, entry_equity=balance,
                _quantity=qty, _stop=float(event["initial_sl"]), _stop_stage=-1,
                _max_fav_r=0.0, _max_adv_r=0.0)
        # no intrabar reentry after stop until a new confirmed Flip
    if pos is not None:
        rec={k:v for k,v in pos.items() if not k.startswith("_")}
        rec.update(exit_time=pd.NaT,exit_price=math.nan,exit_reason="OPEN",
                   realized_r=math.nan,gross_r=math.nan,cost_r=math.nan,
                   highest_reached_r=pos["_max_fav_r"],maximum_adverse_r=pos["_max_adv_r"],
                   max_target_hit=min(4,int(math.floor(max(0,pos["_max_fav_r"])))),
                   final_protected_r=pos["_stop_stage"], duration_hours=math.nan,
                   quantity=pos["_quantity"],gross_usdt=math.nan,cost_usdt=math.nan,
                   net_usdt=math.nan,equity_after_exit=math.nan)
        if warmup_cutoff is None or rec["entry_time"]>=warmup_cutoff:
            out.append(rec)
    return pd.DataFrame(out)


def run_both(minute: pd.DataFrame, p: Params, warmup_cutoff: Optional[pd.Timestamp] = None) -> tuple[pd.DataFrame,pd.DataFrame]:
    hourly=hourly_from_1m(minute)
    plans=make_flip_plans(hourly,p)
    a=run_version(hourly,minute,plans,p,"A",warmup_cutoff)
    c=run_version(hourly,minute,plans,p,"C",warmup_cutoff)
    return plans,pd.concat([a,c],ignore_index=True)


def cost_summary(trades: pd.DataFrame) -> dict:
    settled=trades[trades.exit_reason!="OPEN"].copy()
    if settled.empty:
        return {"closed":0,"net_r":0,"fee_and_slippage_r":0,"win_rate":None,"pf_r":None}
    r=settled.realized_r.astype(float)
    # 僅為已平倉權益回撤，絕不混稱持倉中 MTM 回撤。
    settled=settled.sort_values("exit_time")
    if "equity_after_exit" in settled and "entry_equity" in settled:
        first=float(settled.iloc[0].entry_equity)
        equity=np.r_[first,settled.equity_after_exit.to_numpy(dtype=float)]
        peaks=np.maximum.accumulate(equity)
        drawdowns=np.where(peaks>0,(peaks-equity)/peaks,np.nan)
        realized_mdd=float(np.nanmax(drawdowns))
        ending_equity=float(equity[-1])
    else:
        realized_mdd=None
        ending_equity=None
    total_gains=r[r>0].sum()
    total_losses=-r[r<0].sum()
    return dict(closed=int(len(settled)),net_r=float(r.sum()),mean_r=float(r.mean()),
                realized_only_mdd_pct=100*realized_mdd if realized_mdd is not None else None,
                ending_equity=ending_equity,
                total_cost_usdt=float(settled.cost_usdt.sum()) if "cost_usdt" in settled else None,
                win_rate=float((r>0).mean()),pf_r=float(total_gains/total_losses) if total_losses>0 else None,
                fee_and_slippage_r=float(settled.cost_r.sum()),
                initial_stop_count=int((settled.exit_reason=="Initial SL").sum()),
                flip_count=int(settled.exit_reason.str.startswith("Flip").sum()))


def chop_diagnostics(plans: pd.DataFrame, trades: pd.DataFrame, hours=(6,12,24)) -> dict:
    """不偷看未來當濾器；此處只做事後摩擦統計。"""
    flips=plans.sort_values("signal_close_time")
    gap_h=flips.signal_close_time.diff().dt.total_seconds()/3600 if len(flips) else pd.Series(dtype=float)
    results={f"flip_within_{h}h":int((gap_h<=h).sum()) for h in hours}
    results["all_flips"]=int(len(flips))
    results["three_flip_cycles_within_24h"]=int(sum((flips.iloc[i].sign==flips.iloc[i-2].sign and
       (flips.iloc[i].signal_close_time-flips.iloc[i-2].signal_close_time)<=pd.Timedelta(hours=24))
       for i in range(2,len(flips))))
    for v in ("A","C"):
        ts=trades[(trades.version==v)&(trades.exit_reason!="OPEN")]
        fast_lose={str(h):{"trades":int((ts.duration_hours<=h).sum()),
                  "net_r":float(ts.loc[ts.duration_hours<=h,"realized_r"].sum()),
                  "fees_r":float(ts.loc[ts.duration_hours<=h,"cost_r"].sum())} for h in hours}
        results[v]={"rapid_trade_windows":fast_lose,
                    "closed_under_12h":int((ts.duration_hours<12).sum()),
                    "closed_under_24h":int((ts.duration_hours<24).sum()),
                    "closed_with_max_below_1R":int((ts.highest_reached_r<1).sum()),
                    **cost_summary(ts)}
    return results


def stop_missed_opportunities(minute: pd.DataFrame, plans: pd.DataFrame, trades: pd.DataFrame,
                              version: str="A") -> pd.DataFrame:
    """診斷3ATR截短後被掃、後續到下一個Flip前能否再回到進場、是否到1R/2R。

    事後 MFE 不等於可實現收益；這個指標為『錯失候選』，須另以大SL對照回測證實。
    """
    ts=trades[(trades.version==version)&(trades.exit_reason=="Initial SL")&(trades.stop_bound=="max")]
    flips=sorted(pd.to_datetime(plans.signal_close_time,utc=True))
    results=[]
    for trade in ts.itertuples(index=False):
        end_candidates=[t for t in flips if t>trade.exit_time]
        if not end_candidates:
            continue
        end=end_candidates[0]
        future=minute[(minute.index>trade.exit_time)&(minute.index<end)]
        if future.empty:
            continue
        sign=trade.sign
        favourable=(float(future.high.max())-trade.entry_price) if sign==1 else (trade.entry_price-float(future.low.min()))
        results.append(dict(version=version,trade_id=trade.trade_id, side=trade.side,
          entry_time=trade.entry_time,stop_time=trade.exit_time,next_flip_time=end,
          stop_risk_atr=trade.risk_atr,raw_risk_atr=trade.raw_risk_atr,
          recovered_entry=bool(favourable>=0),post_stop_max_fav_r=float(favourable/trade.initial_risk),
          later_reached_1R=bool(favourable>=trade.initial_risk),
          later_reached_2R=bool(favourable>=2*trade.initial_risk)))
    return pd.DataFrame(results)


def paired_atr_caps(minute: pd.DataFrame, p: Params, caps=(3.0,4.0,5.0),
                    warmup_cutoff: Optional[pd.Timestamp]=None) -> tuple[pd.DataFrame,dict]:
    """各情境重新配置同一固定資金風險，並依相同Flip訊號交易；未改進場參數。"""
    hourly=hourly_from_1m(minute)
    results=[]
    for cap in caps:
        pp=replace(p,maximum_stop_atr=float(cap))
        plans=make_flip_plans(hourly,pp)
        for version in ("A","C"):
            run=run_version(hourly,minute,plans,pp,version,warmup_cutoff)
            run["atr_cap"] = cap
            results.append(run)
    all_trades=pd.concat(results,ignore_index=True)
    summaries={str(cap):{v:cost_summary(all_trades[(all_trades.atr_cap==cap)&(all_trades.version==v)])
                  for v in ("A","C")} for cap in caps}
    return all_trades,summaries
