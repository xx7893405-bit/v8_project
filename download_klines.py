import os
import time
from pathlib import Path
import pandas as pd
import requests

DATA_DIR = Path("202101-202607_merged")
START_STR = "2021-01-01 00:00:00"
END_STR = "2026-07-07 00:00:00"

SYMBOLS = {
    "eth": "ETHUSDT",
    "sol": "SOLUSDT"
}

TIMEFRAMES = ["15m", "1h", "4h", "1d"]

def fetch_klines(symbol: str, interval: str, start_ms: int, end_ms: int):
    url = "https://api.binance.com/api/v3/klines"
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": 1000,
        "startTime": start_ms,
        "endTime": end_ms
    }
    response = requests.get(url, params=params, timeout=20)
    response.raise_for_status()
    return response.json()

def download_data(symbol: str, interval: str, prefix: str):
    print(f"🚀 Downloading {symbol} ({interval}) from {START_STR} to {END_STR}...")
    start_ms = int(pd.Timestamp(START_STR).timestamp() * 1000)
    end_ms = int(pd.Timestamp(END_STR).timestamp() * 1000)
    
    all_klines = []
    current_start = start_ms
    
    while current_start < end_ms:
        try:
            klines = fetch_klines(symbol, interval, current_start, end_ms)
            if not klines:
                break
            all_klines.extend(klines)
            last_time = int(klines[-1][0])
            
            if last_time >= end_ms or len(klines) < 1000:
                break
                
            current_start = last_time + 1
            time.sleep(0.1)
        except Exception as exc:
            print(f"❌ Error fetching {symbol} {interval}: {exc}. Retrying in 2 seconds...")
            time.sleep(2)
            
    if not all_klines:
        print(f"⚠️ No data fetched for {symbol} {interval}")
        return
        
    df = pd.DataFrame(
        all_klines,
        columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_asset_volume", "number_of_trades",
            "taker_buy_base_asset_volume", "taker_buy_quote_asset_volume", "ignore"
        ]
    )
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
        
    df["datetime"] = pd.to_datetime(df["open_time"], unit="ms")
    df.set_index("datetime", inplace=True)
    df = df[["open", "high", "low", "close", "volume"]]
    df = df[~df.index.duplicated(keep="first")].sort_index()
    
    output_path = DATA_DIR / f"{prefix}_{interval}.csv"
    df.to_csv(output_path)
    print(f"💾 Saved {len(df)} rows to {output_path} (Range: {df.index[0]} to {df.index[-1]})")

def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for prefix, symbol in SYMBOLS.items():
        for tf in TIMEFRAMES:
            download_data(symbol, tf, prefix)

if __name__ == "__main__":
    main()
