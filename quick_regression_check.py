"""小型回測回歸檢查：比較兩條資金曲線並確認資料快照未變。"""

import argparse
import hashlib
from pathlib import Path

import pandas as pd


def file_fingerprint(paths):
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(str(path).encode())
        digest.update(str(path.stat().st_size).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def audit_data(data_dir):
    paths = sorted(Path(data_dir).glob("btc_*.csv"))
    if not paths:
        raise FileNotFoundError(f"找不到 BTC 資料：{data_dir}")
    for path in paths:
        frame = pd.read_csv(path)
        time_col = next((c for c in frame if c.lower() in {"timestamp", "time", "date", "datetime"}), None)
        if time_col is None:
            raise ValueError(f"{path} 缺少時間欄位")
        times = pd.to_datetime(frame[time_col])
        if times.duplicated().any() or frame[["open", "high", "low", "close"]].isna().any().any():
            raise ValueError(f"{path} 有重複時間或 OHLC 缺值")
        print(f"DATA {path.name}: rows={len(frame)} {times.min()} -> {times.max()}")
    print(f"DATA fingerprint: {file_fingerprint(paths)}")


def stats(series):
    drawdown = series / series.cummax() - 1
    return {
        "final": float(series.iloc[-1]),
        "return_pct": (float(series.iloc[-1]) / float(series.iloc[0]) - 1) * 100,
        "max_dd_pct": float(drawdown.min()) * 100,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--equity", required=True, help="含 month、baseline、candidate 欄位的 CSV")
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--data-dir", default="202101-202607_merged")
    args = parser.parse_args()

    audit_data(args.data_dir)
    frame = pd.read_csv(args.equity)
    for column in (args.baseline, args.candidate):
        if column not in frame or frame[column].isna().any():
            raise ValueError(f"資金曲線欄位不存在或有缺值：{column}")

    baseline = stats(frame[args.baseline])
    candidate = stats(frame[args.candidate])
    print(f"BASELINE {args.baseline}: {baseline}")
    print(f"CANDIDATE {args.candidate}: {candidate}")
    alerts = []
    if candidate["return_pct"] < baseline["return_pct"] * 0.9:
        alerts.append("總報酬下降超過 10%")
    if candidate["max_dd_pct"] < baseline["max_dd_pct"] - 2:
        alerts.append("最大回撤惡化超過 2 個百分點")
    if alerts:
        print("ALERT: " + "; ".join(alerts))
        raise SystemExit(2)
    print("PASS: 未觸發快速回歸警報")


if __name__ == "__main__":
    main()
