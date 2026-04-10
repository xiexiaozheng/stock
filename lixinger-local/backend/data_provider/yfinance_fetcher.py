"""
YFinanceFetcher — Yahoo Finance 数据源 Fetcher (Priority 4)

数据来源: yfinance 库 (Yahoo Finance API)

特点:
  - 免费、全球市场覆盖
  - A股代码格式: 600519.SS (上海) / 000001.SZ (深圳)
  - 数据 T+1，部分延迟
  - 不需要 Token

防封禁策略:
  - 随机休眠 1.5-3.0 秒
  - 自适应限流 (via error_classifier)
"""
import logging
import time
from datetime import datetime
from typing import Optional

import pandas as pd

from data_provider.base import (
    BaseFetcher,
    DataFetchError,
    STANDARD_COLUMNS,
    normalize_stock_code,
)
from data_provider.error_classifier import (
    classify_error,
    ErrorCategory,
    get_adaptive_limiter,
)

logger = logging.getLogger(__name__)


class YFinanceFetcher(BaseFetcher):
    """
    Yahoo Finance 数据源 Fetcher

    日K线: yf.download() / Ticker.history()
    股票列表: 不支持 (Yahoo 不提供 A 股全市场列表)

    A股代码映射:
      600519 → 600519.SS (上海)
      000001 → 000001.SZ (深圳)
    """

    name = "YFinanceFetcher"
    priority = 4

    def __init__(self):
        super().__init__()
        self._yf = None
        self._limiter = get_adaptive_limiter(
            "yfinance", base_interval=1.5, max_interval=30.0
        )

    def _get_yf(self):
        """延迟导入 yfinance"""
        if self._yf is None:
            import yfinance as yf
            self._yf = yf
        return self._yf

    def _to_yf_symbol(self, stock_code: str) -> str:
        """
        转换为 Yahoo Finance A 股代码格式:
          600519 → 600519.SS (上海证券交易所)
          000001 → 000001.SZ (深圳证券交易所)
        """
        code = normalize_stock_code(stock_code)
        if code.startswith(("6", "9")):
            return f"{code}.SS"
        return f"{code}.SZ"

    # ---- 日K线 (必须实现) ----

    def _fetch_raw_data(
        self,
        stock_code: str,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        """
        通过 yfinance 获取日K线数据。

        yf.download(tickers, start, end)
        """
        self._limiter.wait()

        yf_symbol = self._to_yf_symbol(stock_code)

        try:
            yf = self._get_yf()
            logger.info(
                f"[YFinanceFetcher] yf.download"
                f"({yf_symbol}, {start_date}, {end_date})"
            )
            t0 = time.time()

            df = yf.download(
                tickers=yf_symbol,
                start=start_date,
                end=end_date,
                auto_adjust=True,
                progress=False,
            )

            elapsed = time.time() - t0

            if df is not None and not df.empty:
                self._limiter.record_success()
                logger.info(
                    f"[YFinanceFetcher] download 成功: "
                    f"{len(df)} 行, {elapsed:.2f}s"
                )
                # yfinance 返回 MultiIndex columns 时，取第一级
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                df = df.reset_index()
                return df
            else:
                logger.warning(
                    f"[YFinanceFetcher] {yf_symbol} 返回空数据"
                )
                return pd.DataFrame()

        except Exception as e:
            category = self._limiter.record_error(e)
            if category == ErrorCategory.API_SYNTAX:
                logger.error(
                    f"[YFinanceFetcher] API 语法错误，停止: {e}"
                )
            else:
                logger.warning(
                    f"[YFinanceFetcher] download 失败 [{category.value}]: {e}"
                )
            return pd.DataFrame()

    def _normalize_data(
        self,
        df: pd.DataFrame,
        stock_code: str,
    ) -> pd.DataFrame:
        """将 yfinance 列名映射到标准列名"""
        if df is None or df.empty:
            return pd.DataFrame(columns=STANDARD_COLUMNS)

        col_map = {
            "Date": "date",
            "date": "date",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
            "Adj Close": "close",  # yfinance auto_adjust=True 时已调整
        }

        df = df.rename(
            columns={k: v for k, v in col_map.items() if k in df.columns}
        )

        # 日期格式
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")

        # yfinance 不直接返回 pct_chg 和 amount，需要计算
        if "close" in df.columns and "pct_chg" not in df.columns:
            df["pct_chg"] = df["close"].pct_change() * 100

        if "amount" not in df.columns:
            df["amount"] = None  # Yahoo Finance 不提供成交额

        for col in STANDARD_COLUMNS:
            if col not in df.columns:
                df[col] = None

        return df[STANDARD_COLUMNS]

    # ---- 股票名称 ----

    def get_stock_name(self, stock_code: str) -> Optional[str]:
        """通过 yfinance 获取股票名称"""
        self._limiter.wait()
        try:
            yf = self._get_yf()
            ticker = yf.Ticker(self._to_yf_symbol(stock_code))
            info = ticker.info
            self._limiter.record_success()
            return info.get("shortName") or info.get("longName")
        except Exception as e:
            self._limiter.record_error(e)
            logger.warning(f"[YFinanceFetcher] 获取名称失败: {e}")
            return None
