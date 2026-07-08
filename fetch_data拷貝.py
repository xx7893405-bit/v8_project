import time
import pandas as pd
import requests


def fetch_binance_klines(symbol="BTCUSDT", interval="15m", limit=1000, start_time=None):
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    if start_time:
        params["startTime"] = start_time

    response = requests.get(url, params=params)
    response.raise_for_status()
    data = response.json()
    return data


def get_historical_data(symbol="BTCUSDT", interval="15m", days=30):
    print(f"開始從幣安 API 獲取 {symbol} 的 {interval} K線數據 (回溯 {days} 天)...")
    all_klines = []

    now_ms = int(time.time() * 1000)
    start_ms = now_ms - (days * 24 * 60 * 60 * 1000)

    current_start = start_ms
    while True:
        try:
            klines = fetch_binance_klines(
                symbol=symbol,
                interval=interval,
                limit=1000,
                start_time=current_start,
            )
            if not klines:
                break
            all_klines.extend(klines)

            last_time = klines[-1][0]
            if last_time >= now_ms or len(klines) < 1000:
                break
            current_start = last_time + 1
            time.sleep(0.3)
        except Exception as e:
            print(f"獲取數據時出錯: {e}")
            break

    if not all_klines:
        print(f"未獲取到任何 {interval} 數據。")
        return None

    # 解析為 DataFrame
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

    # 轉為浮點數
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)

    # 時間轉換
    df["datetime"] = pd.to_datetime(df["open_time"], unit="ms")
    df.set_index("datetime", inplace=True)

    # 僅保留需要的欄位
    df = df[["open", "high", "low", "close", "volume"]]

    # 去重與排序
    df = df[~df.index.duplicated(keep="first")]
    df.sort_index(inplace=True)

    print(f"成功獲取 {len(df)} 根 K線。時間範圍: {df.index[0]} 至 {df.index[-1]}")
    return df


if __name__ == "__main__":
    # 抓取 4 個時段的資料並保存為 CSV
    configs = [
        {"interval": "1m", "days": 365, "filename": "btc_1m.csv"},
        #{"interval": "15m", "days": 365, "filename": "btc_15m.csv"},
        #{"interval": "1h", "days": 365, "filename": "btc_1h.csv"},
        #{"interval": "4h", "days": 365, "filename": "btc_4h.csv"},
        {"interval": "1d", "days": 365, "filename": "btc_1d.csv"},
    ]

    for config in configs:
        df = get_historical_data(interval=config["interval"], days=config["days"])
        if df is not None:
            df.to_csv(config["filename"])
            print(f"數據已儲存至 {config['filename']}\n")
