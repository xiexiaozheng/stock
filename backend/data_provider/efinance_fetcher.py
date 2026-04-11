"""
EfinanceFetcher — efinance 库数据源 Fetcher

参考 ZhuLinsen/daily_stock_analysis data_provider/efinance_fetcher.py

数据来源: efinance 库（基于东方财富 API 封装, 免费无需 Token）

特点:
  - 免费、无限速
  - 数据全面（日K线、实时行情、板块信息）
  - 接口简洁

防封禁策略:
  - 随机休眠 1.5-3.0 秒（比 akshare 更轻量）
  - User-Agent 随机轮换
  - 超时保护（默认 10 秒）
  - 熔断器保护
"""
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

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
from utils.akshare_runtime import execute_with_proxy_retry

logger = logging.getLogger(__name__)


class EfinanceFetcher(BaseFetcher):
    """
    efinance 数据源 Fetcher

    日K线: ef.stock.get_quote_history()
    实时行情: ef.stock.get_realtime_quotes()
    板块: ef.stock.get_belong_board()
    """

    name = "EfinanceFetcher"
    framework_key = "efinance"

    def __init__(self, timeout: float = 10.0):
        super().__init__()
        self.timeout = timeout
        self._ef = None

    def _get_ef(self):
        """延迟导入 efinance"""
        if self._ef is None:
            import efinance as ef
            self._ef = ef
        return self._ef

    def _execute_with_retry(self, operation_name: str, func):
        return execute_with_proxy_retry(
            "Efinance",
            operation_name,
            func,
            max_attempts=2,
            backoff_seconds=1.0,
        )

    # ---- 防封禁 ----

    def _enforce_rate_limit(self) -> None:
        """轻量限流: 1.5-3.0 秒"""
        self.random_sleep(1.5, 3.0)
        self._last_request_time = time.time()

    # ---- 日K线 (必须实现) ----

    def _fetch_raw_data(
        self,
        stock_code: str,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        """
        通过 efinance 获取日K线数据

        ef.stock.get_quote_history(stock_codes, beg, end)
        """
        self._enforce_rate_limit()
        try:
            logger.info(
                f"[EfinanceFetcher] ef.stock.get_quote_history"
                f"({stock_code}, {start_date}, {end_date})"
            )
            t0 = time.time()

            beg = start_date.replace("-", "")
            end = end_date.replace("-", "")

            df = self._execute_with_retry(
                "stock.get_quote_history",
                lambda: self._get_ef().stock.get_quote_history(
                    stock_codes=stock_code,
                    beg=beg,
                    end=end,
                ),
            )

            elapsed = time.time() - t0
            if df is not None and not df.empty:
                logger.info(
                    f"[EfinanceFetcher] get_quote_history 成功: "
                    f"{len(df)} 行, {elapsed:.2f}s"
                )
                return df
            else:
                logger.warning("[EfinanceFetcher] get_quote_history 返回空数据")
                return pd.DataFrame()
        except Exception as e:
            logger.warning(f"[EfinanceFetcher] get_quote_history 失败: {e}")
            return pd.DataFrame()

    def _normalize_data(
        self,
        df: pd.DataFrame,
        stock_code: str,
    ) -> pd.DataFrame:
        """将 efinance 列名映射到标准列名"""
        if df is None or df.empty:
            return pd.DataFrame(columns=STANDARD_COLUMNS)

        col_map = {
            "日期": "date",
            "开盘": "open",
            "最高": "high",
            "最低": "low",
            "收盘": "close",
            "成交量": "volume",
            "成交额": "amount",
            "涨跌幅": "pct_chg",
            # efinance 英文列名
            "date": "date",
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "volume": "volume",
            "amount": "amount",
            "pct_chg": "pct_chg",
        }

        df = df.rename(
            columns={k: v for k, v in col_map.items() if k in df.columns}
        )

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
        通过 efinance 获取实时行情

        ef.stock.get_realtime_quotes([stock_code])
        """
        self._enforce_rate_limit()
        code = normalize_stock_code(stock_code)
        try:
            df = self._execute_with_retry(
                "stock.get_realtime_quotes",
                lambda: self._get_ef().stock.get_realtime_quotes([code]),
            )
            if df is None or df.empty:
                return None

            r = df.iloc[0]
            return UnifiedRealtimeQuote(
                code=code,
                name=str(r.get("股票名称", r.get("name", ""))),
                source=RealtimeSource.EFINANCE,
                price=safe_float(r.get("最新价", r.get("price"))),
                change_pct=safe_float(r.get("涨跌幅", r.get("pct_chg"))),
                change_amount=safe_float(r.get("涨跌额", r.get("change"))),
                volume=safe_int(r.get("成交量", r.get("volume"))),
                amount=safe_float(r.get("成交额", r.get("amount"))),
                turnover_rate=safe_float(r.get("换手率", r.get("turnover_rate"))),
                amplitude=safe_float(r.get("振幅", r.get("amplitude"))),
                open_price=safe_float(r.get("今开", r.get("open"))),
                high=safe_float(r.get("最高", r.get("high"))),
                low=safe_float(r.get("最低", r.get("low"))),
                pre_close=safe_float(r.get("昨收", r.get("pre_close"))),
            )
        except Exception as e:
            logger.warning(f"[EfinanceFetcher] 实时行情失败: {e}")
            return None

    # ---- 股票名称 ----

    def get_stock_name(self, stock_code: str) -> Optional[str]:
        """从实时行情获取股票名称"""
        quote = self.get_realtime_quote(stock_code)
        return quote.name if quote and quote.name else None

    # ---- 板块信息 ----

    def get_base_info(self, stock_code: str) -> Optional[Dict[str, Any]]:
        """
        获取股票基本信息 (PE, PB, ROE, 行业等)

        ef.stock.get_base_info(stock_code)
        """
        self._enforce_rate_limit()
        try:
            code = normalize_stock_code(stock_code)
            info = self._execute_with_retry(
                "stock.get_base_info",
                lambda: self._get_ef().stock.get_base_info(code),
            )
            if info is not None:
                return dict(info) if hasattr(info, "to_dict") else info
        except Exception as e:
            logger.warning(f"[EfinanceFetcher] get_base_info 失败: {e}")
        return None

    # ---- 市场统计 ----

    def get_market_stats(self) -> Optional[Dict[str, Any]]:
        """
        获取市场涨跌统计

        计算涨停、跌停、上涨、下跌家数
        """
        self._enforce_rate_limit()
        try:
            df = self._execute_with_retry(
                "stock.get_realtime_quotes",
                lambda: self._get_ef().stock.get_realtime_quotes(),
            )
            if df is None or df.empty:
                return None

            pct_col = None
            for c in ("涨跌幅", "pct_chg"):
                if c in df.columns:
                    pct_col = c
                    break
            if pct_col is None:
                return None

            pcts = pd.to_numeric(df[pct_col], errors="coerce").dropna()

            return {
                "total": len(pcts),
                "up": int((pcts > 0).sum()),
                "down": int((pcts < 0).sum()),
                "flat": int((pcts == 0).sum()),
                "limit_up": int((pcts >= 9.9).sum()),
                "limit_down": int((pcts <= -9.9).sum()),
            }
        except Exception as e:
            logger.warning(f"[EfinanceFetcher] 市场统计失败: {e}")
            return None

    # ---- 板块排名 ----

    def get_sector_rankings(
        self,
        n: int = 5,
    ) -> Optional[Tuple[List[Dict], List[Dict]]]:
        """
        获取行业板块涨跌排名

        :return: (top_n_涨, top_n_跌) 或 None
        """
        self._enforce_rate_limit()
        try:
            df = self._execute_with_retry(
                "stock.get_realtime_quotes",
                lambda: self._get_ef().stock.get_realtime_quotes(["行业板块"]),
            )
            if df is None or df.empty:
                return None

            pct_col = None
            name_col = None
            for c in ("涨跌幅", "pct_chg"):
                if c in df.columns:
                    pct_col = c
                    break
            for c in ("板块名称", "name", "股票名称"):
                if c in df.columns:
                    name_col = c
                    break

            if not pct_col or not name_col:
                return None

            df[pct_col] = pd.to_numeric(df[pct_col], errors="coerce")
            df = df.dropna(subset=[pct_col])

            top = df.nlargest(n, pct_col)
            bottom = df.nsmallest(n, pct_col)

            def _to_list(sub_df):
                return [
                    {
                        "name": str(row.get(name_col, "")),
                        "pct_chg": safe_float(row.get(pct_col)),
                    }
                    for _, row in sub_df.iterrows()
                ]

            return _to_list(top), _to_list(bottom)
        except Exception as e:
            logger.warning(f"[EfinanceFetcher] 板块排名失败: {e}")
            return None
