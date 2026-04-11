"""
LongbridgeFetcher — Longbridge (长桥) 数据源 Fetcher

数据来源: Longbridge OpenAPI SDK

特点:
  - 需要 App Key + App Secret + Access Token
  - 支持港股、美股、A股（沪港通/深港通标的）
  - 实时和历史行情
  - 有免费额度

配置 (环境变量):
  LONGBRIDGE_APP_KEY: App Key
  LONGBRIDGE_APP_SECRET: App Secret
  LONGBRIDGE_ACCESS_TOKEN: Access Token

A股代码映射:
  600519 → 600519.SH (上海)
  000001 → 000001.SZ (深圳)
"""
import logging
import os
import time
from typing import Optional

import pandas as pd

from data_provider.base import (
    BaseFetcher,
    DataFetchError,
    STANDARD_COLUMNS,
    normalize_stock_code,
)
from data_provider.error_classifier import (
    ErrorCategory,
    get_adaptive_limiter,
)

logger = logging.getLogger(__name__)


class LongbridgeFetcher(BaseFetcher):
    """
    Longbridge (长桥) 数据源 Fetcher

    日K线: QuoteContext.history_candlesticks()
    实时行情: QuoteContext.quote()
    股票列表: 不直接支持 (仅支持已关注标的)

    需要环境变量:
      LONGBRIDGE_APP_KEY, LONGBRIDGE_APP_SECRET, LONGBRIDGE_ACCESS_TOKEN
    """

    name = "LongbridgeFetcher"
    framework_key = "longbridge"

    def __init__(self):
        super().__init__()
        self._ctx = None
        self._config = None
        self._available = None  # None = 未检测
        self._limiter = get_adaptive_limiter(
            "longbridge", base_interval=1.0, max_interval=30.0
        )

    def _is_configured(self) -> bool:
        """检查是否配置了 Longbridge 凭证"""
        return bool(
            os.getenv("LONGBRIDGE_APP_KEY")
            and os.getenv("LONGBRIDGE_APP_SECRET")
            and os.getenv("LONGBRIDGE_ACCESS_TOKEN")
        )

    def _get_context(self):
        """延迟初始化 Longbridge QuoteContext"""
        if self._ctx is None:
            if not self._is_configured():
                raise DataFetchError(
                    "Longbridge 未配置: 需要设置 LONGBRIDGE_APP_KEY, "
                    "LONGBRIDGE_APP_SECRET, LONGBRIDGE_ACCESS_TOKEN"
                )
            try:
                from longport.openapi import Config, QuoteContext
                self._config = Config.from_env()
                self._ctx = QuoteContext(self._config)
            except Exception as e:
                self._available = False
                raise DataFetchError(f"Longbridge 初始化失败: {e}")
        return self._ctx

    def _to_lb_symbol(self, stock_code: str) -> str:
        """
        转换为 Longbridge A 股代码格式:
          600519 → 600519.SH
          000001 → 000001.SZ
        """
        code = normalize_stock_code(stock_code)
        if code.startswith(("6", "9")):
            return f"{code}.SH"
        return f"{code}.SZ"

    # ---- 日K线 (必须实现) ----

    def _fetch_raw_data(
        self,
        stock_code: str,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        """
        通过 Longbridge SDK 获取日K线数据。

        ctx.history_candlesticks(symbol, period, count, adjust_type)
        """
        if self._available is False:
            return pd.DataFrame()

        if not self._is_configured():
            logger.debug("[LongbridgeFetcher] 未配置凭证，跳过")
            return pd.DataFrame()

        self._limiter.wait()

        try:
            from longport.openapi import Period, AdjustType
            ctx = self._get_context()
            symbol = self._to_lb_symbol(stock_code)

            logger.info(
                f"[LongbridgeFetcher] history_candlesticks"
                f"({symbol}, {start_date}, {end_date})"
            )
            t0 = time.time()

            # Longbridge SDK 使用 count 而非日期范围
            # 计算大致天数
            from datetime import datetime
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
            days = (end_dt - start_dt).days + 1
            count = min(max(days, 30), 1000)

            candlesticks = ctx.history_candlesticks(
                symbol=symbol,
                period=Period.Day,
                count=count,
                adjust_type=AdjustType.ForwardAdjust,
            )

            elapsed = time.time() - t0

            if not candlesticks:
                logger.warning(f"[LongbridgeFetcher] {symbol} 返回空数据")
                return pd.DataFrame()

            # 转换为 DataFrame
            rows = []
            for c in candlesticks:
                date_str = str(c.timestamp)[:10] if hasattr(c, "timestamp") else ""
                rows.append({
                    "date": date_str,
                    "open": float(c.open) if hasattr(c, "open") else None,
                    "high": float(c.high) if hasattr(c, "high") else None,
                    "low": float(c.low) if hasattr(c, "low") else None,
                    "close": float(c.close) if hasattr(c, "close") else None,
                    "volume": int(c.volume) if hasattr(c, "volume") else None,
                    "amount": float(c.turnover) if hasattr(c, "turnover") else None,
                })

            df = pd.DataFrame(rows)

            # 按日期过滤
            if not df.empty and "date" in df.columns:
                df = df[(df["date"] >= start_date) & (df["date"] <= end_date)]

            self._limiter.record_success()
            logger.info(
                f"[LongbridgeFetcher] 成功: {len(df)} 行, {elapsed:.2f}s"
            )
            return df

        except ImportError:
            self._available = False
            logger.warning("[LongbridgeFetcher] longport 包未安装")
            return pd.DataFrame()
        except DataFetchError:
            raise
        except Exception as e:
            category = self._limiter.record_error(e)
            if category == ErrorCategory.API_SYNTAX:
                self._available = False
                logger.error(
                    f"[LongbridgeFetcher] API 错误，标记不可用: {e}"
                )
            else:
                logger.warning(
                    f"[LongbridgeFetcher] 获取失败 [{category.value}]: {e}"
                )
            return pd.DataFrame()

    def _normalize_data(
        self,
        df: pd.DataFrame,
        stock_code: str,
    ) -> pd.DataFrame:
        """Longbridge 数据已经是标准格式，直接补全缺失列"""
        if df is None or df.empty:
            return pd.DataFrame(columns=STANDARD_COLUMNS)

        # 计算涨跌幅
        if "close" in df.columns and "pct_chg" not in df.columns:
            df["pct_chg"] = df["close"].pct_change() * 100

        for col in STANDARD_COLUMNS:
            if col not in df.columns:
                df[col] = None

        return df[STANDARD_COLUMNS]

    def close(self) -> None:
        """释放 Longbridge 连接"""
        self._ctx = None
        self._config = None
