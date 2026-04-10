"""
EastmoneyFetcher — 东方财富直连 API Fetcher (Priority 6)

直接调用东方财富公开 HTTP API，不通过 akshare。

数据来源: 东方财富公开 HTTP API
  - 日K线: push2his.eastmoney.com/api/qt/stock/kline/get
  - 实时行情: push2.eastmoney.com/api/qt/stock/get

特点:
  - 无需依赖 akshare
  - 免费公开接口
  - 直连更灵活，可控制反爬策略

防封禁策略:
  - 随机 User-Agent
  - 自适应限流
  - 请求间隔 2-5 秒
"""
import logging
import random
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd

from data_provider.base import (
    BaseFetcher,
    DataFetchError,
    STANDARD_COLUMNS,
    normalize_stock_code,
)
from data_provider.realtime_types import (
    UnifiedRealtimeQuote,
    RealtimeSource,
    safe_float,
    safe_int,
)
from data_provider.error_classifier import (
    ErrorCategory,
    get_adaptive_limiter,
)

logger = logging.getLogger(__name__)

# User-Agent 池
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) "
    "Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

# 东方财富市场代码映射
_MARKET_MAP = {
    "sh": "1",  # 上海
    "sz": "0",  # 深圳
    "bj": "0",  # 北京 (使用深圳通道)
}


def _get_secid(stock_code: str) -> str:
    """
    生成东方财富 secid:
      600519 → 1.600519 (上海)
      000001 → 0.000001 (深圳)
    """
    code = normalize_stock_code(stock_code)
    if code.startswith(("6", "9")):
        return f"1.{code}"
    return f"0.{code}"


class EastmoneyFetcher(BaseFetcher):
    """
    东方财富直连 API Fetcher

    不依赖 akshare, 直接调用东财公开 HTTP API。

    日K线: push2his.eastmoney.com/api/qt/stock/kline/get
    实时行情: push2.eastmoney.com/api/qt/stock/get
    """

    name = "EastmoneyFetcher"
    priority = 6

    # 日K线历史 API
    KLINE_URL = (
        "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    )
    # 实时行情 API
    QUOTE_URL = (
        "https://push2.eastmoney.com/api/qt/stock/get"
    )

    def __init__(self):
        super().__init__()
        self._session = None
        self._limiter = get_adaptive_limiter(
            "eastmoney_direct", base_interval=2.0, max_interval=30.0
        )

    def _get_session(self):
        """延迟创建 requests Session"""
        if self._session is None:
            import requests
            self._session = requests.Session()
            self._session.headers.update({
                "User-Agent": random.choice(_USER_AGENTS),
                "Referer": "https://quote.eastmoney.com/",
                "Accept": "application/json",
            })
        else:
            # 随机更换 UA
            self._session.headers["User-Agent"] = random.choice(_USER_AGENTS)
        return self._session

    # ---- 日K线 (必须实现) ----

    def _fetch_raw_data(
        self,
        stock_code: str,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        """
        直连东方财富获取日K线数据。

        API: push2his.eastmoney.com/api/qt/stock/kline/get
        """
        self._limiter.wait()

        secid = _get_secid(stock_code)
        beg = start_date.replace("-", "")
        end = end_date.replace("-", "")

        params = {
            "secid": secid,
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": "101",       # 日K
            "fqt": "1",         # 前复权
            "beg": beg,
            "end": end,
            "lmt": "5000",      # 最大返回条数
            "ut": "fa5fd1943c7b386f172d6893dbbd4dc0",
        }

        try:
            session = self._get_session()
            logger.info(
                f"[EastmoneyFetcher] 直连东财日K线: "
                f"secid={secid}, {start_date}~{end_date}"
            )
            t0 = time.time()

            resp = session.get(
                self.KLINE_URL, params=params, timeout=15
            )
            resp.raise_for_status()
            data = resp.json()

            elapsed = time.time() - t0

            klines = data.get("data", {}).get("klines", [])
            if not klines:
                logger.warning(f"[EastmoneyFetcher] {secid} 返回空K线数据")
                return pd.DataFrame()

            rows = []
            for line in klines:
                parts = line.split(",")
                if len(parts) >= 11:
                    rows.append({
                        "date": parts[0],           # 日期
                        "open": parts[1],            # 开盘
                        "close": parts[2],           # 收盘
                        "high": parts[3],            # 最高
                        "low": parts[4],             # 最低
                        "volume": parts[5],          # 成交量
                        "amount": parts[6],          # 成交额
                        "amplitude": parts[7],       # 振幅
                        "pct_chg": parts[8],         # 涨跌幅
                        "change_amount": parts[9],   # 涨跌额
                        "turnover_rate": parts[10],  # 换手率
                    })

            df = pd.DataFrame(rows)
            self._limiter.record_success()

            logger.info(
                f"[EastmoneyFetcher] 直连日K线成功: "
                f"{len(df)} 行, {elapsed:.2f}s"
            )
            return df

        except Exception as e:
            category = self._limiter.record_error(e)
            if category == ErrorCategory.API_SYNTAX:
                logger.error(
                    f"[EastmoneyFetcher] API 语法错误: {e}"
                )
            else:
                logger.warning(
                    f"[EastmoneyFetcher] 日K线获取失败 [{category.value}]: {e}"
                )
            return pd.DataFrame()

    def _normalize_data(
        self,
        df: pd.DataFrame,
        stock_code: str,
    ) -> pd.DataFrame:
        """东财直连数据列名已接近标准"""
        if df is None or df.empty:
            return pd.DataFrame(columns=STANDARD_COLUMNS)

        for col in STANDARD_COLUMNS:
            if col not in df.columns:
                df[col] = None

        return df[STANDARD_COLUMNS]

    # ---- 实时行情 ----

    def get_realtime_quote(
        self,
        stock_code: str,
        source: str = "default",
    ) -> Optional[UnifiedRealtimeQuote]:
        """
        直连东方财富获取实时行情。
        """
        self._limiter.wait()
        code = normalize_stock_code(stock_code)
        secid = _get_secid(code)

        params = {
            "secid": secid,
            "fields": (
                "f43,f44,f45,f46,f47,f48,f50,f51,f52,f55,"
                "f57,f58,f60,f116,f117,f162,f167,f168,f169,f170"
            ),
            "ut": "fa5fd1943c7b386f172d6893dbbd4dc0",
        }

        try:
            session = self._get_session()
            resp = session.get(
                self.QUOTE_URL, params=params, timeout=10
            )
            resp.raise_for_status()
            data = resp.json().get("data", {})

            if not data:
                return None

            self._limiter.record_success()

            return UnifiedRealtimeQuote(
                code=code,
                name=str(data.get("f58", "")),
                source=RealtimeSource.AKSHARE_EM,  # 同为东方财富来源
                price=safe_float(data.get("f43")),
                change_pct=safe_float(data.get("f170")),
                change_amount=safe_float(data.get("f169")),
                volume=safe_int(data.get("f47")),
                amount=safe_float(data.get("f48")),
                volume_ratio=safe_float(data.get("f50")),
                turnover_rate=safe_float(data.get("f168")),
                amplitude=safe_float(data.get("f55")),
                open_price=safe_float(data.get("f46")),
                high=safe_float(data.get("f44")),
                low=safe_float(data.get("f45")),
                pre_close=safe_float(data.get("f60")),
                pe_ratio=safe_float(data.get("f162")),
                pb_ratio=safe_float(data.get("f167")),
                total_mv=safe_float(data.get("f116")),
                circ_mv=safe_float(data.get("f117")),
            )

        except Exception as e:
            self._limiter.record_error(e)
            logger.warning(f"[EastmoneyFetcher] 实时行情失败: {e}")
            return None

    def close(self) -> None:
        """关闭 session"""
        if self._session:
            try:
                self._session.close()
            except Exception:
                pass
            self._session = None
