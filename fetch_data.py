import argparse
import time
from pathlib import Path
from typing import Optional

import pandas as pd
import requests


DEFAULT_SYMBOL = "BTCUSDT"
DEFAULT_LIMIT = 1000
DEFAULT_THROTTLE_SECONDS = 0.2
DEFAULT_RANGES = [
    {
        "label": "202407-2507",
        "start": "2024-07-01 00:00:00",
        "end": "2025-07-31 23:59:59",
    },
    {
        "label": "202507-2607",
        "start": "2025-07-01 00:00:00",
        "end": "2026-07-31 23:59:59",
    },
]


def fetch_binance_klines(
    symbol: str = DEFAULT_SYMBOL,
    interval: str = "15m",
    limit: int = DEFAULT_LIMIT,
    start_time: Optional[int] = None,
    end_time: Optional[int] = None,
):
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    if start_time is not None:
        params["startTime"] = start_time
    if end_time is not None:
        params["endTime"] = end_time

    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def get_historical_data_by_range(
    symbol: str = DEFAULT_SYMBOL,
    interval: str = "15m",
    start_str: str = "2024-07-01 00:00:00",
    end_str: str = "2025-07-31 23:59:59",
) -> Optional[pd.DataFrame]:
    print(
        f"🚀 開始從幣安 API 獲取 {symbol} 的 {interval} K 線數據 "
        f"(範圍: {start_str} 至 {end_str})..."
    )
    all_klines = []

    start_ms = int(pd.Timestamp(start_str).timestamp() * 1000)
    end_ms = int(pd.Timestamp(end_str).timestamp() * 1000)

    current_start = start_ms
    while current_start < end_ms:
        try:
            klines = fetch_binance_klines(
                symbol=symbol,
                interval=interval,
                limit=DEFAULT_LIMIT,
                start_time=current_start,
                end_time=end_ms,
            )
            if not klines:
                break

            all_klines.extend(klines)
            last_time = int(klines[-1][0])
            print(
                f"  已抓取 {len(all_klines):>7} 根，"
                f"最新 K 線時間 {pd.to_datetime(last_time, unit='ms')}"
            )

            if last_time >= end_ms or len(klines) < DEFAULT_LIMIT:
                break

            current_start = last_time + 1
            time.sleep(DEFAULT_THROTTLE_SECONDS)
        except Exception as exc:
            print(f"❌ 獲取數據時出錯: {exc}")
            break

    if not all_klines:
        print(f"⚠️ 未獲取到任何 {interval} 數據。")
        return None

    df = pd.DataFrame(
        all_klines,
        columns=[
            "open_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "close_time",
            "quote_asset_volume",
            "number_of_trades",
            "taker_buy_base_asset_volume",
            "taker_buy_quote_asset_volume",
            "ignore",
        ],
    )

    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)

    df["datetime"] = pd.to_datetime(df["open_time"], unit="ms")
    df.set_index("datetime", inplace=True)
    df = df[["open", "high", "low", "close", "volume"]]
    df = df[~df.index.duplicated(keep="first")].sort_index()

    print(f"📊 成功獲取 {len(df)} 根 K 線。實際範圍: {df.index[0]} 至 {df.index[-1]}")
    return df


def save_range_csv(base_dir: Path, interval: str, range_cfg: dict, symbol: str) -> None:
    output_dir = base_dir / range_cfg["label"]
    output_dir.mkdir(parents=True, exist_ok=True)

    df = get_historical_data_by_range(
        symbol=symbol,
        interval=interval,
        start_str=range_cfg["start"],
        end_str=range_cfg["end"],
    )
    if df is None:
        return

    output_path = output_dir / f"btc_{interval}.csv"
    df.to_csv(output_path)
    print(f"💾 數據已儲存至 {output_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="從 Binance 抓取指定區間 BTC K 線資料。")
    parser.add_argument(
        "--interval",
        default="5m",
        help="K 線級別，例如 5m / 15m / 1h / 4h / 1d。",
    )
    parser.add_argument(
        "--symbol",
        default=DEFAULT_SYMBOL,
        help="交易對，預設 BTCUSDT。",
    )
    parser.add_argument(
        "--base-dir",
        default=".",
        help="輸出根目錄，預設為目前工作目錄。",
    )
    parser.add_argument(
        "--single-range",
        action="store_true",
        help="只抓單一區間，搭配 --start / --end / --label 使用。",
    )
    parser.add_argument("--start", help="單一區間起始時間，例如 2024-07-01 00:00:00。")
    parser.add_argument("--end", help="單一區間結束時間，例如 2025-07-31 23:59:59。")
    parser.add_argument("--label", help="單一區間輸出資料夾名稱。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    base_dir = Path(args.base_dir)

    if args.single_range:
        if not args.start or not args.end or not args.label:
            raise ValueError("--single-range 需要同時提供 --start、--end、--label。")
        ranges = [{"label": args.label, "start": args.start, "end": args.end}]
    else:
        ranges = DEFAULT_RANGES

    for range_cfg in ranges:
        print("-" * 60)
        print(f"📦 準備抓取 {range_cfg['label']} / {args.interval}")
        save_range_csv(base_dir=base_dir, interval=args.interval, range_cfg=range_cfg, symbol=args.symbol)


if __name__ == "__main__":
    main()
