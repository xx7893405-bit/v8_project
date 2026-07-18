import unittest

import pandas as pd

from api_market_data import ApiFeedConfig, ExchangeApiMarketDataFeed


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse(self.payload)


class ExchangeApiMarketDataContractTest(unittest.TestCase):
    @staticmethod
    def _binance_row(open_ms, close_ms, close):
        return [open_ms, "1", "3", "0", str(close), "10", close_ms, "0", 1, "0", "0", "0"]

    def test_binance_uses_perpetual_endpoint_and_excludes_open_candle(self):
        now_ms = int(pd.Timestamp.utcnow().timestamp() * 1000)
        feed = ExchangeApiMarketDataFeed(ApiFeedConfig(symbol="BTCUSDT"))
        feed.session = FakeSession(
            [
                self._binance_row(now_ms - 120_000, now_ms - 60_001, 2),
                self._binance_row(now_ms - 60_000, now_ms + 60_000, 3),
            ]
        )

        result = feed._fetch_binance_ohlcv("1m", 1)

        self.assertEqual(result["close"].tolist(), [2.0])
        url, request = feed.session.calls[0]
        self.assertEqual(url, "https://fapi.binance.com/fapi/v1/klines")
        self.assertEqual(request["params"]["symbol"], "BTCUSDT")

    def test_okx_swap_feed_excludes_unconfirmed_candle(self):
        now_ms = int(pd.Timestamp.utcnow().timestamp() * 1000)
        feed = ExchangeApiMarketDataFeed(ApiFeedConfig())
        feed.session = FakeSession(
            {"data": [
                [str(now_ms - 120_000), "1", "3", "0", "2", "10", "0", "0", "1"],
                [str(now_ms - 60_000), "2", "4", "1", "3", "10", "0", "0", "0"],
            ]}
        )

        result = feed._fetch_okx_ohlcv("1m", 1)

        self.assertEqual(result["close"].tolist(), [2.0])
        _, request = feed.session.calls[0]
        self.assertEqual(request["params"]["instId"], "BTC-USDT-SWAP")

    def test_resample_keeps_only_complete_bucket(self):
        complete = pd.date_range("2026-01-01 00:00:00", periods=5, freq="1min")
        incomplete = pd.date_range("2026-01-01 00:05:00", periods=4, freq="1min")
        index = complete.append(incomplete)
        source = pd.DataFrame(
            {"open": 1.0, "high": 2.0, "low": 0.0, "close": 1.0, "volume": 1.0},
            index=index,
        )

        result = ExchangeApiMarketDataFeed._resample_from_15m(source, "5m")

        self.assertEqual(list(result.index), [pd.Timestamp("2026-01-01 00:00:00")])


if __name__ == "__main__":
    unittest.main()
