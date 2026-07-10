#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import traceback
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional


SERVER_NAME = "coingecko-local"
SERVER_VERSION = "0.1.0"
DEFAULT_PROTOCOL_VERSION = "2024-11-05"
BASE_URL = "https://api.coingecko.com/api/v3"


TOOLS = [
    {
        "name": "search_coins",
        "description": "Search CoinGecko coin ids by keyword, symbol, or project name.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search keyword such as btc, bitcoin, eth, solana, pepe.",
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_coin_price",
        "description": "Fetch simple spot price and optional market stats for one or more CoinGecko ids.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "CoinGecko ids, for example ['bitcoin', 'ethereum'].",
                },
                "vs_currency": {
                    "type": "string",
                    "description": "Quote currency such as usd, twd, btc.",
                    "default": "usd",
                },
                "include_market_cap": {"type": "boolean", "default": True},
                "include_24hr_vol": {"type": "boolean", "default": True},
                "include_24hr_change": {"type": "boolean", "default": True},
                "include_last_updated_at": {"type": "boolean", "default": True},
            },
            "required": ["ids"],
        },
    },
    {
        "name": "get_coin_markets",
        "description": "Fetch market snapshots such as current price, market cap rank, volume, and 24h change.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "vs_currency": {"type": "string", "default": "usd"},
                "ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional CoinGecko ids to filter.",
                },
                "category": {"type": "string"},
                "order": {
                    "type": "string",
                    "default": "market_cap_desc",
                },
                "per_page": {
                    "type": "integer",
                    "default": 25,
                    "minimum": 1,
                    "maximum": 250,
                },
                "page": {"type": "integer", "default": 1, "minimum": 1},
                "sparkline": {"type": "boolean", "default": False},
                "price_change_percentage": {
                    "type": "string",
                    "description": "Comma-separated values such as 1h,24h,7d,14d,30d,200d,1y.",
                },
            },
        },
    },
    {
        "name": "get_coin_ohlc",
        "description": "Fetch OHLC candles for a coin id and lookback window. Useful for higher timeframe research.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "CoinGecko id such as bitcoin."},
                "vs_currency": {"type": "string", "default": "usd"},
                "days": {
                    "description": "Lookback days such as 1, 7, 14, 30, 90, 180, 365, or max.",
                    "oneOf": [{"type": "integer"}, {"type": "string"}],
                    "default": 30,
                },
            },
            "required": ["id"],
        },
    },
    {
        "name": "get_coin_market_chart_range",
        "description": "Fetch historical price, market cap, and volume between two Unix timestamps. Best fit for backtest ingestion.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "CoinGecko id such as bitcoin."},
                "vs_currency": {"type": "string", "default": "usd"},
                "from_timestamp": {
                    "type": "integer",
                    "description": "Unix timestamp in seconds.",
                },
                "to_timestamp": {
                    "type": "integer",
                    "description": "Unix timestamp in seconds.",
                },
            },
            "required": ["id", "from_timestamp", "to_timestamp"],
        },
    },
]


class McpError(Exception):
    def __init__(self, code: int, message: str, data: Optional[Any] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


def json_dumps(payload: Dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def write_message(payload: Dict[str, Any]) -> None:
    body = json_dumps(payload)
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    sys.stdout.buffer.write(header)
    sys.stdout.buffer.write(body)
    sys.stdout.buffer.flush()


def read_message() -> Optional[Dict[str, Any]]:
    headers: Dict[str, str] = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n"):
            break
        decoded = line.decode("utf-8").strip()
        if ":" not in decoded:
            continue
        key, value = decoded.split(":", 1)
        headers[key.strip().lower()] = value.strip()

    content_length = headers.get("content-length")
    if content_length is None:
        raise McpError(-32700, "Missing Content-Length header.")

    try:
        size = int(content_length)
    except ValueError as exc:
        raise McpError(-32700, "Invalid Content-Length header.") from exc

    body = sys.stdin.buffer.read(size)
    if not body:
        return None

    try:
        return json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise McpError(-32700, f"Invalid JSON payload: {exc}") from exc


def to_jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    return value


def make_text_result(data: Any) -> Dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(to_jsonable(data), ensure_ascii=False, indent=2),
            }
        ]
    }


def get_api_headers() -> Dict[str, str]:
    headers = {
        "accept": "application/json",
        "user-agent": f"{SERVER_NAME}/{SERVER_VERSION}",
    }
    pro_key = os.getenv("COINGECKO_API_KEY") or os.getenv("COINGECKO_PRO_API_KEY")
    demo_key = os.getenv("COINGECKO_DEMO_API_KEY")
    if pro_key:
        headers["x-cg-pro-api-key"] = pro_key
    elif demo_key:
        headers["x-cg-demo-api-key"] = demo_key
    return headers


def http_get_json(path: str, params: Optional[Dict[str, Any]] = None) -> Any:
    query = ""
    if params:
        filtered = {k: v for k, v in params.items() if v is not None}
        query = urllib.parse.urlencode(filtered, doseq=True)

    url = f"{BASE_URL}{path}"
    if query:
        url = f"{url}?{query}"

    request = urllib.request.Request(url, headers=get_api_headers(), method="GET")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise McpError(exc.code, f"CoinGecko HTTP {exc.code}: {body[:400]}")
    except urllib.error.URLError as exc:
        raise McpError(-32000, f"CoinGecko network error: {exc.reason}") from exc


def require_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise McpError(-32602, f"'{field}' must be a non-empty string.")
    return value.strip()


def require_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise McpError(-32602, f"'{field}' must be an integer.")
    return value


def require_string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise McpError(-32602, f"'{field}' must be a non-empty array of strings.")
    normalized = []
    for item in value:
        normalized.append(require_string(item, field))
    return normalized


def handle_search_coins(arguments: Dict[str, Any]) -> Dict[str, Any]:
    query = require_string(arguments.get("query"), "query")
    payload = http_get_json("/search", {"query": query})
    coins = payload.get("coins", [])
    trimmed = [
        {
            "id": coin.get("id"),
            "symbol": coin.get("symbol"),
            "name": coin.get("name"),
            "market_cap_rank": coin.get("market_cap_rank"),
            "thumb": coin.get("thumb"),
        }
        for coin in coins[:20]
    ]
    return make_text_result({"query": query, "coins": trimmed})


def handle_get_coin_price(arguments: Dict[str, Any]) -> Dict[str, Any]:
    ids = require_string_list(arguments.get("ids"), "ids")
    params = {
        "ids": ",".join(ids),
        "vs_currencies": arguments.get("vs_currency", "usd"),
        "include_market_cap": str(arguments.get("include_market_cap", True)).lower(),
        "include_24hr_vol": str(arguments.get("include_24hr_vol", True)).lower(),
        "include_24hr_change": str(arguments.get("include_24hr_change", True)).lower(),
        "include_last_updated_at": str(arguments.get("include_last_updated_at", True)).lower(),
    }
    payload = http_get_json("/simple/price", params)
    return make_text_result(payload)


def handle_get_coin_markets(arguments: Dict[str, Any]) -> Dict[str, Any]:
    ids = arguments.get("ids")
    if ids is not None:
        ids = require_string_list(ids, "ids")
        ids = ",".join(ids)

    per_page = arguments.get("per_page", 25)
    page = arguments.get("page", 1)
    if isinstance(per_page, bool) or not isinstance(per_page, int):
        raise McpError(-32602, "'per_page' must be an integer.")
    if isinstance(page, bool) or not isinstance(page, int):
        raise McpError(-32602, "'page' must be an integer.")

    params = {
        "vs_currency": arguments.get("vs_currency", "usd"),
        "ids": ids,
        "category": arguments.get("category"),
        "order": arguments.get("order", "market_cap_desc"),
        "per_page": per_page,
        "page": page,
        "sparkline": str(arguments.get("sparkline", False)).lower(),
        "price_change_percentage": arguments.get("price_change_percentage"),
    }
    payload = http_get_json("/coins/markets", params)
    return make_text_result(payload)


def handle_get_coin_ohlc(arguments: Dict[str, Any]) -> Dict[str, Any]:
    coin_id = require_string(arguments.get("id"), "id")
    days = arguments.get("days", 30)
    if isinstance(days, bool) or not isinstance(days, (int, str)):
        raise McpError(-32602, "'days' must be an integer or string.")

    params = {
        "vs_currency": arguments.get("vs_currency", "usd"),
        "days": days,
    }
    payload = http_get_json(f"/coins/{urllib.parse.quote(coin_id)}/ohlc", params)
    return make_text_result(
        {
            "id": coin_id,
            "vs_currency": params["vs_currency"],
            "days": days,
            "candles": payload,
        }
    )


def handle_get_coin_market_chart_range(arguments: Dict[str, Any]) -> Dict[str, Any]:
    coin_id = require_string(arguments.get("id"), "id")
    from_timestamp = require_int(arguments.get("from_timestamp"), "from_timestamp")
    to_timestamp = require_int(arguments.get("to_timestamp"), "to_timestamp")
    if to_timestamp <= from_timestamp:
        raise McpError(-32602, "'to_timestamp' must be greater than 'from_timestamp'.")

    params = {
        "vs_currency": arguments.get("vs_currency", "usd"),
        "from": from_timestamp,
        "to": to_timestamp,
    }
    payload = http_get_json(f"/coins/{urllib.parse.quote(coin_id)}/market_chart/range", params)
    return make_text_result(
        {
            "id": coin_id,
            "vs_currency": params["vs_currency"],
            "from_timestamp": from_timestamp,
            "to_timestamp": to_timestamp,
            "prices": payload.get("prices", []),
            "market_caps": payload.get("market_caps", []),
            "total_volumes": payload.get("total_volumes", []),
        }
    )


TOOL_HANDLERS = {
    "search_coins": handle_search_coins,
    "get_coin_price": handle_get_coin_price,
    "get_coin_markets": handle_get_coin_markets,
    "get_coin_ohlc": handle_get_coin_ohlc,
    "get_coin_market_chart_range": handle_get_coin_market_chart_range,
}


def handle_request(message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    method = message.get("method")
    params = message.get("params", {})
    request_id = message.get("id")

    if method == "notifications/initialized":
        return None

    if method == "initialize":
        requested_version = params.get("protocolVersion") or DEFAULT_PROTOCOL_VERSION
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": requested_version,
                "capabilities": {
                    "tools": {
                        "listChanged": False,
                    }
                },
                "serverInfo": {
                    "name": SERVER_NAME,
                    "version": SERVER_VERSION,
                },
            },
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOLS}}

    if method == "tools/call":
        name = params.get("name")
        if name not in TOOL_HANDLERS:
            raise McpError(-32602, f"Unknown tool: {name}")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise McpError(-32602, "'arguments' must be an object.")
        result = TOOL_HANDLERS[name](arguments)
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    if request_id is None:
        return None

    raise McpError(-32601, f"Method not found: {method}")


def make_error_response(request_id: Any, exc: Exception) -> Dict[str, Any]:
    if isinstance(exc, McpError):
        error = {"code": exc.code, "message": exc.message}
        if exc.data is not None:
            error["data"] = exc.data
    else:
        error = {
            "code": -32603,
            "message": str(exc) or exc.__class__.__name__,
            "data": {"traceback": traceback.format_exc(limit=10)},
        }

    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def main() -> int:
    while True:
        try:
            message = read_message()
            if message is None:
                return 0
            request_id = message.get("id")
            response = handle_request(message)
            if response is not None:
                write_message(response)
        except Exception as exc:
            request_id = None
            if "message" in locals() and isinstance(message, dict):
                request_id = message.get("id")
            write_message(make_error_response(request_id, exc))


if __name__ == "__main__":
    raise SystemExit(main())
