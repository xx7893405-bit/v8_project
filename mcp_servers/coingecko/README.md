# CoinGecko MCP for Codex

This folder contains a local MCP server that exposes CoinGecko data to Codex over stdio.

## Included tools

- `search_coins`
- `get_coin_price`
- `get_coin_markets`
- `get_coin_ohlc`
- `get_coin_market_chart_range`

## Why this setup fits backtesting

- It keeps your strategy code and data connector separate.
- It can be used directly inside Codex prompts for research and iteration.
- It supports public CoinGecko access now, while leaving room for API keys later.

## Optional environment variables

- `COINGECKO_API_KEY`
- `COINGECKO_PRO_API_KEY`
- `COINGECKO_DEMO_API_KEY`

If a key is present, the server will send it using the matching CoinGecko header.

## Register in Codex

Run this from Terminal:

```bash
/Applications/Codex.app/Contents/Resources/codex mcp add coingecko-local -- python3 /Users/jillix/Desktop/v8_project/mcp_servers/coingecko/coingecko_mcp_server.py
```

Then restart the Codex thread or open a new one.

## Example prompts in Codex

```text
用 coingecko-local 幫我查 bitcoin 與 ethereum 當前價格和 24h 漲跌
```

```text
用 coingecko-local 抓 bitcoin 從 2024-07-01 到 2025-07-01 的 market chart range，整理成我回測可用的時間序列格式
```

```text
先 search_coins 找 PEPE 的正確 CoinGecko id，再抓市場資料
```
