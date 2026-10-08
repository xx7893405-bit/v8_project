import math
import unittest
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from boswaves_v8 import (
  Params, _alma, _pine_atr, hourly_from_1m, make_flip_plans,
  validate_ohlcv, run_version, cost_summary, stop_missed_opportunities, chop_diagnostics
)
from run_boswaves_v8 import tv_csv, audit_tv_reference, reconcile


def minute_series(hours=3):
    ix = pd.date_range("2026-09-01",periods=60*hours,freq="1min",tz="UTC")
    return pd.DataFrame(dict(open=100.,high=100.,low=100.,close=100.),index=ix)


def flip_plan(minutes, when, side="LONG", entry=100., risk=1., atr=1.0, raw_sl=95.):
    sign=1 if side=="LONG" else -1
    at=pd.Timestamp(when,tz="UTC")
    return dict(signal_open_time=at-pd.Timedelta(hours=1),signal_close_time=at,
                side=side,sign=sign,entry_price=entry,atr=atr,
                raw_structure_sl=raw_sl,raw_risk_atr=abs(entry-raw_sl)/atr,
                initial_sl=entry-sign*risk, initial_risk=risk,risk_atr=risk/atr,stop_bound="max")


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.p=Params(fee_per_side=.0005,entry_slippage_usd=0.,stop_slippage_usd=0.,flip_slippage_usd=0.)

    def test_alma_weights_last_more_at_offset_high(self):
        p=Params(alma_length=5,alma_offset=.85,alma_sigma=6)
        price=pd.Series([1,1,1,1,5],dtype=float)
        output=_alma(price,p)
        self.assertTrue(math.isnan(output.iloc[3]))
        self.assertGreater(output.iloc[4],price.mean())

    def test_wilder_atr_is_seeded_not_simple_rolling(self):
        idx=pd.date_range("2026-09-01",periods=5,freq="1h",tz="UTC")
        f=pd.DataFrame(dict(open=[10]*5,high=[11,12,13,14,15],low=[9]*5,close=[10]*5),index=idx)
        a=_pine_atr(f,3)
        self.assertTrue(math.isnan(a.iloc[1]))
        self.assertAlmostEqual(a.iloc[2],3.)
        self.assertAlmostEqual(a.iloc[3],(3*2+5)/3)

    def test_partial_hour_fails(self):
        frame=minute_series(3).iloc[:-1]
        with self.assertRaises(ValueError): hourly_from_1m(frame)

    def test_gap_fails(self):
        frame=minute_series(3).drop(minute_series(3).index[13])
        with self.assertRaises(ValueError): validate_ohlcv(frame)

    def test_c_milestone_applies_next_minute_only_and_a_waits_initial_sl(self):
        m=minute_series(3)
        pts=[("2026-09-01 01:01",101.,102.1,101.,102.),
             ("2026-09-01 01:02",102.2,103.1,102.,103.),
             ("2026-09-01 01:03",103.2,104.1,103.,104.),
             ("2026-09-01 01:04",103.,103.,101.9,102.),
             ("2026-09-01 01:05",101.,101.,98.5,99.)]
        for t,o,h,l,c in pts:
            m.loc[pd.Timestamp(t,tz="UTC"),["open","high","low","close"]]=[o,h,l,c]
        plans=pd.DataFrame([flip_plan(m,"2026-09-01 01:00")])
        hourly=hourly_from_1m(m)
        a=run_version(hourly,m,plans,self.p,"A")
        c=run_version(hourly,m,plans,self.p,"C")
        self.assertEqual(a.iloc[0].exit_reason,"Initial SL")
        self.assertEqual(c.iloc[0].exit_reason,"Protect 2R")
        self.assertAlmostEqual(a.iloc[0].exit_price,99.)
        self.assertAlmostEqual(c.iloc[0].exit_price,102.)
        self.assertAlmostEqual(a.iloc[0].gross_r,-1.)
        self.assertAlmostEqual(c.iloc[0].gross_r,2.)
        self.assertEqual(c.iloc[0].max_target_hit,4)
        self.assertGreater(c.iloc[0].cost_r,0.)

    def test_signal_bar_extreme_never_stops_post_close_entry(self):
        m=minute_series(3)
        m.loc[pd.Timestamp("2026-09-01 00:15",tz="UTC"),"low"]=90.
        plans=pd.DataFrame([flip_plan(m,"2026-09-01 01:00")])
        result=run_version(hourly_from_1m(m),m,plans,self.p,"A")
        self.assertEqual(result.iloc[0].exit_reason,"OPEN")

    def test_no_reentry_after_stop_before_next_flip(self):
        m=minute_series(4)
        ix=pd.Timestamp("2026-09-01 01:01",tz="UTC")
        m.loc[ix,["open","high","low","close"]]=[98.,100.,98.,99.]
        plans=pd.DataFrame([flip_plan(m,"2026-09-01 01:00"),flip_plan(m,"2026-09-01 02:00",side="SHORT",raw_sl=105.)])
        result=run_version(hourly_from_1m(m),m,plans,self.p,"A")
        self.assertEqual(len(result),2)
        self.assertEqual(list(result.side),["LONG","SHORT"])
        self.assertEqual(list(result.trade_id),[1,2])
        self.assertAlmostEqual(result.iloc[0].exit_price,98.)  # gap-through stop: not optimistic stop fill

    def test_chop_counts_three_flip_chain(self):
        m=minute_series(4)
        plans=pd.DataFrame([
          flip_plan(m,"2026-09-01 01:00","LONG"),
          flip_plan(m,"2026-09-01 02:00","SHORT"),
          flip_plan(m,"2026-09-01 03:00","LONG")])
        out=run_version(hourly_from_1m(m),m,plans,self.p,"A")
        out_c=run_version(hourly_from_1m(m),m,plans,self.p,"C")
        diag=chop_diagnostics(plans,pd.concat([out,out_c]))
        self.assertEqual(diag["three_flip_cycles_within_24h"],1)
        self.assertEqual(diag["flip_within_6h"],2)

    def test_indicators_past_independent_future_candles(self):
        m=minute_series(80)
        hourly=hourly_from_1m(m)
        z=hourly.copy()
        z.iloc[-1,z.columns.get_loc("close")]=120.
        z.iloc[-1,z.columns.get_loc("high")]=120.
        from boswaves_v8 import indicators
        f1=indicators(hourly,self.p)
        f2=indicators(z,self.p)
        self.assertTrue(np.allclose(f1.alma.iloc[:-1],f2.alma.iloc[:-1],equal_nan=True))
        self.assertTrue(np.array_equal(f1.flip.iloc[:-1].to_numpy(),f2.flip.iloc[:-1].to_numpy()))

    def test_reference_csv_pairs_and_original_stop_bounds(self):
        path=Path(__file__).resolve().parents[1]/"tv_reference/BOSWaves_1h_AC_trades.csv"
        if not path.exists(): self.skipTest("test source CSV not present")
        tv=tv_csv(path)
        data=audit_tv_reference(tv)
        self.assertEqual(data["trade_pairs"],33)
        self.assertEqual(data["tv_rows"],66)
        self.assertEqual(data["pair_entry_mismatch_ids"],[])
        self.assertEqual(data["tv_trade_versions"]["A"]["risk_cap_3atr"],26)

    def test_missing_signals_fail_parity_gate(self):
        path=Path(__file__).resolve().parents[1]/"tv_reference/BOSWaves_1h_AC_trades.csv"
        if not path.exists(): self.skipTest("test source CSV not present")
        reference=tv_csv(path)
        computed=pd.DataFrame(columns=["version","side","entry_time","entry_price","initial_sl","exit_time","exit_reason"])
        matches,summary=reconcile(reference,computed)
        self.assertFalse(summary["passed"])
        self.assertEqual(summary["signal_price_sl_matches"],0)

if __name__=="__main__": unittest.main()
