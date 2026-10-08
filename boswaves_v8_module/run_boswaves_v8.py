"""V8 BOSWaves 單一研究入口。

範例：
  python run_boswaves_v8.py audit --tv-csv tv_reference/BOSWaves_1h_AC_trades.csv
  python run_boswaves_v8.py parity --tv-market BINANCE:BTCUSDT.P \
      --database data/btcusdt_perp_1m_202101_present.duckdb --tv-csv ...
  python run_boswaves_v8.py full --database ... --parity-proof reports/.../parity.json

`full` 默認拒絕在 parity gate 不通過時執行。不得把探索結果描述為正式五年結果。
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import math
from secrets import token_hex

import numpy as np
import pandas as pd

from boswaves_v8 import (
    Params, validate_ohlcv, run_both, cost_summary, chop_diagnostics,
    stop_missed_opportunities, paired_atr_caps
)

CANONICAL_MARKET="BINANCE:BTCUSDT.P"
CANONICAL_DATABASE="data/btcusdt_perp_1m_202101_present.duckdb"
CANONICAL_SYMBOL="BTC/USDT:USDT"


def tv_csv(path: Path) -> pd.DataFrame:
    with path.open(encoding="utf-8-sig",newline="") as f:
        items=list(csv.DictReader(f))
    if not items:
        raise ValueError("empty TradingView CSV")
    df=pd.DataFrame(items)
    required=("trade_id","version","side","entry_time","entry_price","atr",
              "raw_structure_sl","initial_sl","risk_atr","exit_time","exit_price",
              "exit_reason","realized_r")
    missing=set(required)-set(df.columns)
    if missing:
        raise ValueError(f"missing TV columns: {sorted(missing)}")
    for col in ("t1_hit","t2_hit","t3_hit","t4_hit"):
        if col in df.columns:
            df[col]=df[col].astype(str).str.lower().eq("true")
    for col in ("entry_price","atr","raw_structure_sl","initial_sl","risk_atr","exit_price","realized_r","max_r","mae_r"):
        if col not in df.columns: continue
        df[col]=pd.to_numeric(df[col],errors="coerce")
    df["trade_id"]=pd.to_numeric(df.trade_id,errors="raise").astype("int32")
    df["entry_time"]=pd.to_datetime(df.entry_time,utc=True)
    df["exit_time"]=pd.to_datetime(df.exit_time,utc=True,errors="coerce")
    if set(df.version) != {"A","C"}:
        raise ValueError("reference must contain A and C versions")
    if df.duplicated(["version","trade_id"]).any():
        raise ValueError("duplicated reference Trade ID")
    return df.sort_values(["version","entry_time"]).reset_index(drop=True)


def audit_tv_reference(tv: pd.DataFrame) -> dict:
    pairs=tv.pivot(index="trade_id",columns="version",values=["entry_time","side","entry_price","initial_sl","atr"])
    pair_count=len(pairs)
    two_version_paired=set(tv[tv.version=="A"].trade_id)==set(tv[tv.version=="C"].trade_id)
    mismatches=[]
    for tid in sorted(set(tv.trade_id)):
        a=tv[(tv.trade_id==tid)&(tv.version=="A")]
        c=tv[(tv.trade_id==tid)&(tv.version=="C")]
        if a.empty or c.empty:
            mismatches.append(tid);continue
        x,y=a.iloc[0],c.iloc[0]
        if x.side!=y.side or x.entry_time!=y.entry_time or abs(x.entry_price-y.entry_price)>1e-8 or abs(x.initial_sl-y.initial_sl)>1e-7:
            mismatches.append(tid)
    m=tv[tv.version=="A"]
    target_conflicts=[]
    if "max_r" in tv.columns:
        for _,row in tv.iterrows():
            for target in range(1,5):
                col=f"t{target}_hit"
                if col in tv.columns and bool(row[col]) != bool(row.max_r>=target-1e-6):
                    target_conflicts.append(dict(trade_id=int(row.trade_id),version=row.version,
                                                 target=target,flag=bool(row[col]),max_r=float(row.max_r)))
    return dict(version="tv-reference-audit/v1", tv_rows=int(len(tv)),
                trade_pairs=pair_count, matched_pair_ids=two_version_paired,
                pair_entry_mismatch_ids=mismatches,target_maxr_conflicts=target_conflicts,
                tv_entry_from=m.entry_time.min().isoformat(),
                tv_entry_through=m.entry_time.max().isoformat(),
                tv_trade_versions={v:dict(total=int(len(g)),closed=int((g.exit_reason!="OPEN").sum()),
                   net_r=float(g.realized_r.sum()),
                   stopped=int((g.exit_reason=="Initial SL").sum()),
                   risk_cap_3atr=int(np.isclose(g.risk_atr,3).sum()),
                   raw_risk_outside_3atr=int((((g.entry_price-g.raw_structure_sl)*np.where(g.side.eq("LONG"),1.,-1.))/g.atr>3+1e-8).sum()))
                   for v,g in tv.groupby("version")},
                market_in_csv=False, fees_in_csv=False, pine_source_in_csv=False,
                dataset_available_in_repo=False,
                note="僅驗證 TV CSV 的 A/C 配對，尚非本機策略 TradingView 對帳")


def _ts_naive_utc(ts: pd.Timestamp):
    ts=pd.Timestamp(ts)
    return ts.tz_convert("UTC").tz_localize(None) if ts.tzinfo else ts


def load_duckdb_1m(database: Path, start: pd.Timestamp, end_exclusive: pd.Timestamp) -> tuple[pd.DataFrame,dict]:
    """全程只讀指定 V8 原生 Binance 永續 1m；不下載、不補缺、不代換現貨。"""
    import duckdb
    if not database.is_file():
        raise FileNotFoundError(f"V8 本機資料庫不存在：{database}。不能用 Git 的 manifest 代替行情")
    start,end=_ts_naive_utc(start),_ts_naive_utc(end_exclusive)
    if end<=start or start.minute or start.second or end.minute or end.second:
        raise ValueError("UTC start/end must be aligned to complete hour")
    conn=duckdb.connect(str(database),read_only=True)
    try:
        q="""SELECT open_time,open,high,low,close
             FROM ohlcv_1m WHERE exchange = 'binance' AND market_type='swap'
               AND symbol='BTC/USDT:USDT' AND open_time>=? AND open_time<?
             ORDER BY open_time"""
        df=conn.execute(q,[start,end]).df()
    finally:
        conn.close()
    if df.empty:
        raise ValueError("requested V8 perpetual market data not found")
    df["open_time"]=pd.to_datetime(df.open_time,utc=True)
    df=df.set_index("open_time")
    validate_ohlcv(df,require_contiguous=True)
    expected=int((end-start)/pd.Timedelta(minutes=1))
    if len(df)!=expected or df.index[0]!=start.tz_localize("UTC") or df.index[-1]!=end.tz_localize("UTC")-pd.Timedelta(minutes=1):
        raise ValueError(f"incomplete window: need {expected} continuous 1m rows, have {len(df)}; fail closed")
    snapshot=dict(source=str(database),exchange="binance",market_type="swap",symbol=CANONICAL_SYMBOL,
                  from_utc=df.index[0].isoformat(),last_open_utc=df.index[-1].isoformat(),
                  rows=len(df),closed_only_assumed_from_canonical_source=True)
    return df,snapshot


def parameter_hash(p: Params) -> str:
    return hashlib.sha256(json.dumps(asdict(p),sort_keys=True).encode()).hexdigest()


def reconcile(tv: pd.DataFrame, computed: pd.DataFrame, allowed_time_minutes: int=0,
              price_tolerance_pct: float=.0002, sl_tolerance_atr: float=.15) -> tuple[pd.DataFrame,dict]:
    """逐筆以方向、訊號時間、entry、SL 做一次性配對；過多額外 Flip 也算失敗。"""
    matches=[]
    comp=computed.copy()
    comp["entry_time"]=pd.to_datetime(comp.entry_time,utc=True)
    comp["ref_match_id"]=np.nan
    for version in ("A","C"):
        cs=comp[(comp.version==version)].sort_values("entry_time")
        rs=tv[tv.version==version].sort_values("entry_time")
        used=set()
        for _,reference in rs.iterrows():
            # TV 同一根 K 的 signal-close timestamp；若實際 TV 時標是 candle open，則應在 config 修正而非自動硬對。
            eligible=cs[(cs.side==reference.side)&((cs.entry_time-reference.entry_time).abs()<=pd.Timedelta(minutes=allowed_time_minutes))]
            eligible=eligible[~eligible.index.isin(used)]
            if eligible.empty:
                matches.append(dict(version=version,trade_id=int(reference.trade_id),status="missing_signal"))
                continue
            idx=(eligible.entry_price-reference.entry_price).abs().idxmin()
            c=eligible.loc[idx]
            used.add(idx)
            entry_err_pct=abs(c.entry_price-reference.entry_price)/reference.entry_price
            sl_err_atr=abs(c.initial_sl-reference.initial_sl)/reference.atr
            same_exit=(str(c.exit_reason)==str(reference.exit_reason))
            exit_time_diff_minutes=(abs(c.exit_time-reference.exit_time).total_seconds()/60
                      if pd.notna(c.exit_time) and pd.notna(reference.exit_time) else math.nan)
            passed=entry_err_pct<=price_tolerance_pct and sl_err_atr<=sl_tolerance_atr
            matches.append(dict(version=version,trade_id=int(reference.trade_id),status="match" if passed else "price_or_sl_mismatch",
                entry_time=c.entry_time,entry_error_pct=entry_err_pct,sl_error_atr=sl_err_atr,
                same_exit_reason=same_exit,exit_time_difference_minutes=exit_time_diff_minutes,
                expected_entry=reference.entry_price,actual_entry=c.entry_price,
                expected_sl=reference.initial_sl,actual_sl=c.initial_sl))
    df=pd.DataFrame(matches)
    # 全部訊號缺失時，也應正常輸出「對帳失敗」而非欄位不存在例外
    if "same_exit_reason" not in df.columns:
        df["same_exit_reason"]=False
    if "exit_time_difference_minutes" not in df.columns:
        df["exit_time_difference_minutes"]=math.nan
    success=int((df.status=="match").sum())
    a=int((df[df.version=="A"].status=="match").sum())
    c=int((df[df.version=="C"].status=="match").sum())
    n=len(tv)
    comp_in_window=comp[(comp.entry_time>=tv.entry_time.min())&(comp.entry_time<=tv.entry_time.max())]
    extra=max(0,len(comp_in_window)-success)
    match_ratio=success/n if n else 0
    # >=80% 只是第一階段訊號+初始SL合格；正式 parity 還需離場一致。
    exit_matches=int(df[(df.status=="match")&(df.same_exit_reason==True)&(df.exit_time_difference_minutes<=60)].shape[0])
    passed= (a>=math.ceil(0.8*len(tv[tv.version=="A"])) and
             c>=math.ceil(0.8*len(tv[tv.version=="C"])) and
             exit_matches>=math.ceil(.80*n) and
             extra<=math.floor(.20*n))
    report={"passed":passed,"reference_count":n,"signal_price_sl_matches":success,
            "signal_price_sl_match_ratio":round(match_ratio,5),"a_matches":a,"c_matches":c,
            "same_reason_and_within_60m_exit_matches":exit_matches,
            "extra_signals_in_window":extra,
            "time_tolerance_min":allowed_time_minutes,"entry_tolerance_pct":price_tolerance_pct,
            "sl_tolerance_atr":sl_tolerance_atr,
            "note":"配對使用 1h confirmed-close times；TV 市場/成交模型必須事先一致"}
    return df,report


def save_data(path:Path, rows:pd.DataFrame) -> None:
    rows.to_csv(path,index=False,encoding="utf-8-sig")


def write_json(path:Path,data:dict) -> None:
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2,default=str),encoding="utf-8")


def run_dir(root:Path, tag:str)->Path:
    when=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix=token_hex(4)
    d=root/f"{tag}_{when}_{suffix}"
    d.mkdir(parents=True,exist_ok=False)
    return d


def main()->None:
    parser=argparse.ArgumentParser(description="V8 isolated BOSWaves parity-gated research")
    parser.add_argument("mode",choices=["audit","parity","full"])
    parser.add_argument("--tv-csv",type=Path,default=Path("tv_reference/BOSWaves_1h_AC_trades.csv"))
    parser.add_argument("--database",type=Path,default=Path(CANONICAL_DATABASE))
    parser.add_argument("--tv-market",help="必填：TradingView實際市場識別碼；需與V8完全一致")
    parser.add_argument("--start",default="2021-01-01T00:00:00Z",help="UTC 1m 開始（含，使用長暖機）")
    parser.add_argument("--end",default="2026-10-08T00:00:00Z",help="UTC 1m 結束（不含）")
    parser.add_argument("--report-root",type=Path,default=Path("reports/boswaves"))
    parser.add_argument("--parity-proof",type=Path,help="full 模式必填：由 parity 命令產出的通過報告")
    parser.add_argument("--stop-reference-mode",choices=["flip_extremes","rolling_bars"],default="flip_extremes")
    parser.add_argument("--flip-history-full-window",action="store_true")
    parser.add_argument("--min-atr",type=float,default=.75)
    parser.add_argument("--max-atr",type=float,default=3.0)
    args=parser.parse_args()
    tv=tv_csv(args.tv_csv)
    tv_audit=audit_tv_reference(tv)
    dest=run_dir(args.report_root,args.mode)
    write_json(dest/"tv_audit.json",tv_audit)
    if args.mode=="audit":
        write_json(dest/"summary.json",{"status":"TV_CSV_AUDITED_NO_MARKET_DATA",**tv_audit})
        print(f"PASS reference CSV structure; report={dest/'summary.json'}; pairs={tv_audit['trade_pairs']}")
        return
    if args.tv_market != CANONICAL_MARKET:
        raise ValueError(f"TV chart market identity must equal V8 {CANONICAL_MARKET}; got {args.tv_market!r}.")
    p=Params(stop_reference_mode=args.stop_reference_mode,flip_history_full_window=args.flip_history_full_window,
             minimum_stop_atr=args.min_atr,maximum_stop_atr=args.max_atr)
    p.validate()
    digest=parameter_hash(p)
    if args.mode=="full":
        if not args.parity_proof or not args.parity_proof.is_file():
            raise ValueError("full simulation is gated; supply a passed parity.json from the same parameters")
        proof=json.loads(args.parity_proof.read_text(encoding="utf-8"))
        if proof.get("passed") is not True or proof.get("parameter_sha256")!=digest or proof.get("tv_market")!=args.tv_market:
            raise ValueError("parity approval invalid for current parameters/market")
    start=pd.Timestamp(args.start)
    end=pd.Timestamp(args.end)
    if pd.isna(start) or pd.isna(end):
        raise ValueError("invalid range")
    if end < tv.entry_time.max() + pd.Timedelta(hours=1):
        raise ValueError("data window must include all TV comparison entries and subsequent 1h close")
    minute,identity=load_duckdb_1m(args.database,start,end)
    if args.mode=="parity":
        if minute.index[-1]<tv.entry_time.max():
            raise ValueError("V8 dataset ends before last TV trade")
    plans,trades=run_both(minute,p, warmup_cutoff=tv.entry_time.min() if args.mode=="parity" else None)
    config=dict(parameters=asdict(p),parameter_sha256=digest,source_snapshot=identity,
                canonical_market=CANONICAL_MARKET,tv_market=args.tv_market,
                tv_reference=str(args.tv_csv), pine_source_verified=False,
                note="暫用公開描述/第三方實作推定核心；原 TV 策略碼未取得，對帳未通過不得稱同等")
    write_json(dest/"manifest.json",config)
    save_data(dest/"plans.csv",plans)
    save_data(dest/"trades.csv",trades)
    if args.mode=="parity":
        matched,parity=reconcile(tv,trades)
        save_data(dest/"parity_details.csv",matched)
        parity.update(parameter_sha256=digest,tv_market=args.tv_market,
                      dataset_start=identity["from_utc"],dataset_end=identity["last_open_utc"],
                      market_data_source=identity["source"])
        write_json(dest/"parity.json",parity)
        write_json(dest/"summary.json",dict(status="PARITY_PASS" if parity["passed"] else "PARITY_FAILED",
                    parity=parity, versions={v:cost_summary(trades[trades.version==v]) for v in ("A","C")}))
        print(f"parity_passed={parity['passed']} matches={parity['signal_price_sl_matches']}/{parity['reference_count']}; report={dest/'summary.json'}")
    else:
        extended,alt_summaries=paired_atr_caps(minute,p,caps=(3.,4.,5.))
        rescue_cases=[]
        baseline=extended[(extended.version=="A")&(extended.atr_cap==3)&(extended.exit_reason=="Initial SL")&(extended.stop_bound=="max")]
        for cap in (4.,5.):
            comparison=extended[(extended.version=="A")&(extended.atr_cap==cap)]
            for record in baseline.itertuples(index=False):
                match=comparison[(comparison.entry_time==record.entry_time)&(comparison.side==record.side)]
                if not match.empty:
                    candidate=match.iloc[0]
                    rescue_cases.append(dict(atr_cap=cap,entry_time=record.entry_time,
                        original_realized_r=record.realized_r,candidate_realized_r=candidate.realized_r,
                        original_exit=record.exit_reason,candidate_exit=candidate.exit_reason,
                        recovered_as_profitable_flip=bool(str(candidate.exit_reason).startswith("Flip") and candidate.realized_r>0)))
        rescue_df=pd.DataFrame(rescue_cases,columns=["atr_cap","entry_time","original_realized_r","candidate_realized_r",
                                                     "original_exit","candidate_exit","recovered_as_profitable_flip"])
        save_data(dest/"atr_cap_rescues.csv",rescue_df)
        save_data(dest/"atr_caps_trades.csv",extended)
        misses=stop_missed_opportunities(minute,plans,trades,version="A")
        save_data(dest/"post_stop_candidates.csv",misses)
        diag=chop_diagnostics(plans,trades)
        closed=trades[trades.exit_reason!="OPEN"].copy()
        closed["exit_year"]=pd.to_datetime(closed.exit_time,utc=True).dt.year
        by_year={str(year):{v:cost_summary(sub[sub.version==v]) for v in ("A","C")}
                 for year,sub in closed.groupby("exit_year")}
        summary=dict(status="FIVE_YEAR_RESEARCH_ONLY",year_by_year=by_year,counts={v:cost_summary(trades[trades.version==v]) for v in ("A","C")},
                     chop_and_costs=diag,atr_cap_sensitivity=alt_summaries,
                     cap_profitable_recovery_counts={str(cap):int((rescue_df[(rescue_df.atr_cap==cap)].recovered_as_profitable_flip).sum()) for cap in (4.,5.)},
                     post_stop_cases=int(len(misses)),post_stop_reached_entry=int(misses.recovered_entry.sum()) if len(misses) else 0,
                     post_stop_reached_2r=int(misses.later_reached_2R.sum()) if len(misses) else 0,
                     note="本研究只比較固定risk與不同ATR止損上限；不可把停損後回漲當已實現收益；不含歷史funding/mark-price")
        write_json(dest/"summary.json",summary)
        print(f"research report={dest/'summary.json'} post_stop_cases={len(misses)}")


if __name__=="__main__":
    main()
