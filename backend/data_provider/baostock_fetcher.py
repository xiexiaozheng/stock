"""
BaostockFetcher — 证券宝数据源 Fetcher

参考 ZhuLinsen/daily_stock_analysis data_provider/baostock_fetcher.py

数据来源: baostock 库（证券宝, 免费, 无需 Token）

特点:
  - 完全免费
  - 支持后复权因子 (adj_factor)
  - 需要登录/登出会话管理
  - 数据为 T+1（不支持实时行情）
  - 不支持北交所

防封禁: 无需特别防封禁（非爬虫，是接口查询）
"""
import logging
import time
from contextlib import contextmanager
from datetime import datetime
from typing import Optional

import pandas as pd

from data_provider.base import (
    BaseFetcher,
    DataFetchError,
    STANDARD_COLUMNS,
    normalize_stock_code,
    is_bse_code,
)
from data_provider.realtime_types import safe_float
from utils.akshare_runtime import execute_with_proxy_retry

logger = logging.getLogger(__name__)


class BaostockFetcher(BaseFetcher):
    """
    Baostock 数据源 Fetcher

    日K线: bs.query_history_k_data_plus()
    后复权因子: bs.query_adjust_factor()
    股票列表: bs.query_stock_basic()

    限制:
      - 不支持实时行情（T+1 数据）
      - 不支持北交所
      - 需要登录/登出
    """

    name = "BaostockFetcher"
    framework_key = "baostock"
    retry_max_attempts = 2
    retry_backoff_seconds = 1.0

    def __init__(self):
        super().__init__()
        self._bs = None

    @contextmanager
    def _baostock_session(self):
        """
        Baostock 会话上下文管理器。

        自动处理 login/logout 生命周期。
        参考 daily_stock_analysis _baostock_session。
        """
        import baostock as bs
        login_result = bs.login()
        if login_result.error_code != "0":
            raise DataFetchError(
                f"Baostock 登录失败: {login_result.error_msg}"
            )
        try:
            yield bs
        finally:
            bs.logout()

    def _convert_stock_code(self, stock_code: str) -> str:
        """
        转换为 Baostock 格式:
          '600519' → 'sh.600519' (上海)
          '000001' → 'sz.000001' (深圳)

        不支持北交所。
        """
        code = normalize_stock_code(stock_code)
        if is_bse_code(code):
            raise DataFetchError(
                f"Baostock 不支持北交所代码: {code}"
            )

        if code.startswith(("6", "9")):
            return f"sh.{code}"
        return f"sz.{code}"

    def _execute_with_retry(self, operation_name: str, func):
        return execute_with_proxy_retry(
            "Baostock",
            operation_name,
            func,
            max_attempts=self.retry_max_attempts,
            backoff_seconds=self.retry_backoff_seconds,
        )

    # ---- 日K线 (必须实现) ----

    def _fetch_raw_data(
        self,
        stock_code: str,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        """
        通过 Baostock 获取日K线数据。

        使用 bs.query_history_k_data_plus()
        adjustflag = 2 (前复权)
        """
        code = normalize_stock_code(stock_code)
        if is_bse_code(code):
            logger.warning(f"[BaostockFetcher] 不支持北交所: {code}")
            return pd.DataFrame()

        bs_code = self._convert_stock_code(code)
        self.random_sleep(0.5, 1.5)

        try:
            def _query_history() -> pd.DataFrame:
                with self._baostock_session() as bs:
                    logger.info(
                        f"[BaostockFetcher] query_history_k_data_plus"
                        f"({bs_code}, {start_date}, {end_date})"
                    )

                    fields = (
                        "date,open,high,low,close,volume,amount,"
                        "pctChg,turn,isST"
                    )
                    rs = bs.query_history_k_data_plus(
                        code=bs_code,
                        fields=fields,
                        start_date=start_date,
                        end_date=end_date,
                        frequency="d",
                        adjustflag="2",  # 前复权
                    )

                    if rs.error_code != "0":
                        raise DataFetchError(
                            f"{self.name} query_history_k_data_plus 失败: {rs.error_msg}"
                        )

                    data_list = []
                    while rs.error_code == "0" and rs.next():
                        data_list.append(rs.get_row_data())

                    if not data_list:
                        return pd.DataFrame()

                    df = pd.DataFrame(data_list, columns=rs.fields)
                    logger.info(
                        f"[BaostockFetcher] 获取 {len(df)} 行数据"
                    )
                    return df

            return self._execute_with_retry("query_history_k_data_plus", _query_history)

        except DataFetchError:
            raise
        except Exception as e:
            logger.warning(f"[BaostockFetcher] 日K线获取失败: {e}")
            return pd.DataFrame()

    def _normalize_data(
        self,
        df: pd.DataFrame,
        stock_code: str,
    ) -> pd.DataFrame:
        """将 baostock 列名映射到标准列名"""
        if df is None or df.empty:
            return pd.DataFrame(columns=STANDARD_COLUMNS)

        col_map = {
            "date": "date",
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "volume": "volume",
            "amount": "amount",
            "pctChg": "pct_chg",
        }

        df = df.rename(
            columns={k: v for k, v in col_map.items() if k in df.columns}
        )

        for col in STANDARD_COLUMNS:
            if col not in df.columns:
                df[col] = None

        return df[STANDARD_COLUMNS]

    # ---- 后复权因子 ----

    def get_adjust_factor(
        self,
        stock_code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Optional[pd.DataFrame]:
        """
        获取后复权因子。

        这是 BaostockFetcher 的特有功能，其他 Fetcher 无法提供。
        用于填充 DailyMarketValuation.adj_factor 字段。

        返回 DataFrame: [date, adjust_factor, back_adjust_factor]
        """
        code = normalize_stock_code(stock_code)
        if is_bse_code(code):
            return None

        bs_code = self._convert_stock_code(code)

        if start_date is None:
            start_date = "2020-01-01"
        if end_date is None:
            end_date = datetime.today().strftime("%Y-%m-%d")

        self.random_sleep(0.5, 1.0)

        try:
            def _query_adjust_factor() -> Optional[pd.DataFrame]:
                with self._baostock_session() as bs:
                    logger.info(
                        f"[BaostockFetcher] query_adjust_factor"
                        f"({bs_code}, {start_date}, {end_date})"
                    )

                    rs = bs.query_adjust_factor(
                        code=bs_code,
                        start_date=start_date,
                        end_date=end_date,
                    )

                    if rs.error_code != "0":
                        raise DataFetchError(
                            f"{self.name} query_adjust_factor 失败: {rs.error_msg}"
                        )

                    data_list = []
                    while rs.error_code == "0" and rs.next():
                        data_list.append(rs.get_row_data())

                    if not data_list:
                        return None

                    df = pd.DataFrame(data_list, columns=rs.fields)
                    logger.info(
                        f"[BaostockFetcher] 复权因子 {len(df)} 行"
                    )
                    return df

            return self._execute_with_retry("query_adjust_factor", _query_adjust_factor)

        except Exception as e:
            logger.warning(f"[BaostockFetcher] 复权因子获取失败: {e}")
            return None

    # ---- 股票名称 ----

    def get_stock_name(self, stock_code: str) -> Optional[str]:
        """通过 baostock 获取股票名称"""
        code = normalize_stock_code(stock_code)
        if is_bse_code(code):
            return None

        bs_code = self._convert_stock_code(code)

        try:
            def _query_stock_name() -> Optional[str]:
                with self._baostock_session() as bs:
                    rs = bs.query_stock_basic(code=bs_code)
                    if rs.error_code != "0":
                        raise DataFetchError(
                            f"{self.name} query_stock_basic 失败: {rs.error_msg}"
                        )
                    if rs.next():
                        data = rs.get_row_data()
                        if len(data) >= 2:
                            return str(data[1]).strip() or None
                    return None

            return self._execute_with_retry("query_stock_basic", _query_stock_name)
        except Exception as e:
            logger.warning(f"[BaostockFetcher] 股票名称获取失败: {e}")

        return None

    # ---- 股票列表 ----

    def get_stock_list(self) -> Optional[pd.DataFrame]:
        """获取全市场股票列表"""
        try:
            def _query_stock_list() -> Optional[pd.DataFrame]:
                with self._baostock_session() as bs:
                    rs = bs.query_stock_basic()

                    if rs.error_code != "0":
                        raise DataFetchError(
                            f"{self.name} query_stock_basic 失败: {rs.error_msg}"
                        )

                    data_list = []
                    while rs.error_code == "0" and rs.next():
                        data_list.append(rs.get_row_data())

                    if not data_list:
                        return None

                    return pd.DataFrame(data_list, columns=rs.fields)

            return self._execute_with_retry("query_stock_basic", _query_stock_list)
        except Exception as e:
            logger.warning(f"[BaostockFetcher] 股票列表获取失败: {e}")
            return None
