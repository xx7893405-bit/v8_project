import time
import pandas as pd
import requests


def fetch_binance_klines(symbol="BTCUSDT", interval="15m", limit=1000, start_time=None, end_time=None):
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    if start_time:
        params["startTime"] = start_time
    if end_time:
        params["endTime"] = end_time

    response = requests.get(url, params=params)
    response.raise_for_status()
    data = response.json()
    return data


def get_historical_data_by_range(symbol="BTCUSDT", interval="15m", start_str="2024-07-01", end_str="2025-07-31"):
    print(f"🚀 開始從幣安 API 獲取 {symbol} 的 {interval} K線數據 (範圍: {start_str} 至 {end_str})...")
    all_klines = []

    # 將日期字串轉換為毫秒時間戳
    start_ms = int(pd.to_datetime(start_str).timestamp() * 1000)
    end_ms = int(pd.to_datetime(end_str).timestamp() * 1000)

    current_start = start_ms
    while current_start < end_ms:
        try:
            klines = fetch_binance_klines(
                symbol=symbol,
                interval=interval,
                limit=1000,
                start_time=current_start,
                end_time=end_ms
            )
            if not klines:
                break
            all_klines.extend(klines)

            last_time = klines[-1][0]
            # 如果最後一筆時間已經超過結束時間，或者拿到的資料少於 limit，代表收工了
            if last_time >= end_ms or len(klines) < 1000:
                break
                
            current_start = last_time + 1
            time.sleep(0.2)  # 微調權重等待，避免被幣安 IP 封鎖
        except Exception as e:
            print(f"❌ 獲取數據時出錯: {e}")
            break

    if not all_klines:
        print(f"⚠️ 未獲取到任何 {interval} 數據 (注意: 1m 等細顆粒度歷史 API 可能不支援，需下載歷史Zip)。")
        return None

    # 解析為 DataFrame
    df = pd.DataFrame(
        all_klines,
        columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_asset_volume", "number_of_trades",
            "taker_buy_base_asset_volume", "taker_buy_quote_asset_volume", "ignore"
        ]
    )

    # 轉為浮點數
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)

    # 時間轉換
    df["datetime"] = pd.to_datetime(df["open_time"], unit="ms")
    df.set_index("datetime", inplace=True)

    # 僅保留 V8 引擎需要的欄位
    df = df[["open", "high", "low", "close", "volume"]]

    # 去重與排序
    df = df[~df.index.duplicated(keep="first")]
    df.sort_index(inplace=True)

    print(f"📊 成功獲取 {len(df)} 根 K線。實際範圍: {df.index[0]} 至 {df.index[-1]}")
    return df


if __name__ == "__main__":
    # 配置回測所需的四個時段
    # 註：1m 資料若因幣安線上限制抓不完全，請改用之前提供的歷史資料庫下載方案
    configs = [
        #{"interval": "1m", "filename": "btc_1m_2407_2507.csv"},
        #{"interval": "15m", "filename": "btc_15m_2407_2507.csv"},
        #{"interval": "1h", "filename": "btc_1h_2407_2507.csv"},
        #{"interval": "4h", "filename": "btc_4h_2407_2507.csv"},
        {"interval": "1d", "filename": "btc_1d.csv"},
    ]

    for config in configs:
        df = get_historical_data_by_range(
            interval=config["interval"], 
            start_str="2024-07-01 00:00:00", 
            end_str="2025-07-31 23:59:59"
        )
        if df is not None:
            df.to_csv(config["filename"])
            print(f"💾 數據已儲存至 {config['filename']}\n")
        print("-" * 50)