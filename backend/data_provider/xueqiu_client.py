"""雪球数据接口。"""
from __future__ import annotations

import logging
import random
import time
from datetime import datetime
from typing import Any, Dict

import requests

from data_provider.base import normalize_stock_code
from data_provider.error_classifier import get_adaptive_limiter

logger = logging.getLogger(__name__)

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]


def _to_xueqiu_symbol(stock_code: str) -> str:
    code = normalize_stock_code(stock_code)
    if code.startswith(("60", "68")):
        return f"SH{code}"
    if code.startswith(("43", "83", "87", "88", "92")):
        return f"BJ{code}"
    return f"SZ{code}"


class XueqiuClient:
    BASE_URL = "https://stock.xueqiu.com"
    QUOTE_URL = f"{BASE_URL}/v5/stock/quote.json"
    CAPITAL_FLOW_URL = f"{BASE_URL}/v5/stock/capital/distribution.json"

    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update({
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://xueqiu.com/",
            "User-Agent": random.choice(_USER_AGENTS),
        })
        self._limiter = get_adaptive_limiter("xueqiu", base_interval=2.0, max_interval=60.0)
        self._cookie_expires_at = 0.0

    def _ensure_cookie(self, symbol: str) -> None:
        now = time.time()
        if now < self._cookie_expires_at:
            return

        try:
            self._limiter.wait()
            self._session.headers["User-Agent"] = random.choice(_USER_AGENTS)
            response = self._session.get(f"https://xueqiu.com/S/{symbol}", timeout=10)
            response.raise_for_status()
            self._cookie_expires_at = now + 1800
            self._limiter.record_success()
        except Exception as exc:  # noqa: BLE001
            self._limiter.record_error(exc)
            raise

    def _get_json(self, url: str, *, symbol: str, params: Dict[str, Any]) -> Dict[str, Any]:
        try:
            self._ensure_cookie(symbol)
            self._limiter.wait()
            self._session.headers["User-Agent"] = random.choice(_USER_AGENTS)
            response = self._session.get(url, params=params, timeout=10)
            response.raise_for_status()
            payload = response.json()
            self._limiter.record_success()
            if not isinstance(payload, dict):
                raise ValueError("雪球返回结构异常")
            return payload
        except Exception as exc:  # noqa: BLE001
            self._limiter.record_error(exc)
            raise

    def get_bundle(self, stock_code: str) -> Dict[str, Any]:
        symbol = _to_xueqiu_symbol(stock_code)
        quote_payload = self._get_json(
            self.QUOTE_URL,
            symbol=symbol,
            params={"symbol": symbol, "extend": "detail"},
        )
        capital_payload = self._get_json(
            self.CAPITAL_FLOW_URL,
            symbol=symbol,
            params={"symbol": symbol},
        )

        quote = quote_payload.get("data", {}).get("quote", {})
        capital_flow = capital_payload.get("data", {})
        if not isinstance(quote, dict):
            quote = {}
        if not isinstance(capital_flow, dict):
            capital_flow = {}

        logger.debug("雪球数据获取成功: %s", symbol)
        return {
            "symbol": symbol,
            "updated_at": datetime.now().isoformat(),
            "quote": quote,
            "capital_flow": capital_flow,
        }
