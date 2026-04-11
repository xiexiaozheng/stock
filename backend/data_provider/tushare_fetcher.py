"""
TushareFetcher — Tushare Pro 数据源 Fetcher

参考 ZhuLinsen/daily_stock_analysis data_provider/tushare_fetcher.py

数据来源: Tushare Pro API (需要 Token, 免费额度 80次/分钟)

特点:
  - 数据质量高、接口稳定
  - 需要 Token (注册后免费获取)
  - 免费额度限制: 80 次/分钟
  - 支持筹码分布 (cyq_chips, 高级权限)
  - 配置 Token 后可使用更多接口能力

防封禁策略:
  - 每分钟调用计数器 (80次/分钟免费配额)
  - 超出配额自动等待到下一分钟
  - 熔断器保护
"""
import logging
import time
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd

from data_provider.base import (
    BaseFetcher,
    DataFetchError,
    RateLimitError,
    STANDARD_COLUMNS,
    normalize_stock_code,
)
from data_provider.realtime_types import (
    UnifiedRealtimeQuote,
    ChipDistribution,
    RealtimeSource,
    safe_float,
    safe_int,
)
from utils.akshare_runtime import execute_with_proxy_retry

logger = logging.getLogger(__name__)


class TushareFetcher(BaseFetcher):
    """
    Tushare Pro 数据源 Fetcher

    日K线: pro.daily(ts_code, start_date, end_date)
    实时行情: ts.realtime_quote(ts_code)
    筹码分布: pro.cyq_chips(ts_code) (高级权限)
    股票列表: pro.stock_basic()

    限流: 80 次/分钟 (免费配额)
    """

    name = "TushareFetcher"
    framework_key = "tushare"

    # 免费配额: 80 次/分钟
    FREE_QUOTA_PER_MINUTE = 80

    def __init__(self, token: str = ""):
        super().__init__()
        self._token = token
        self._pro = None
        self._ts = None

        # 每分钟调用计数器 (参考 daily_stock_analysis)
        self._call_count_per_minute: Dict[int, int] = {}
        self._rate_lock = threading.Lock()

    def _get_pro(self):
        """延迟初始化 Tushare Pro API"""
        if self._pro is None:
            import tushare as ts
            self._ts = ts
            if self._token:
                ts.set_token(self._token)
            self._pro = ts.pro_api(self._token)
        return self._pro

    # ---- 限流 (每分钟配额) ----

    def _enforce_rate_limit(self) -> None:
        """
        基于每分钟配额的限流策略。

        参考 daily_stock_analysis TushareFetcher._enforce_rate_limit:
        1. 计算当前分钟的调用次数
        2. 如果 >= 80 次，等待到下一分钟
        3. 重置计数器
        """
        with self._rate_lock:
            current_minute = int(time.time() / 60)

            # 清理旧的计数器 (只保留当前分钟)
            expired = [
                m for m in self._call_count_per_minute
                if m < current_minute
            ]
            for m in expired:
                del self._call_count_per_minute[m]

            if current_minute not in self._call_count_per_minute:
                self._call_count_per_minute[current_minute] = 0

            if self._call_count_per_minute[current_minute] >= self.FREE_QUOTA_PER_MINUTE:
                sleep_seconds = 60 - (time.time() % 60) + 1
                logger.warning(
                    f"[TushareFetcher] 达到 {self.FREE_QUOTA_PER_MINUTE} 次/分钟配额，"
                    f"等待 {sleep_seconds:.1f}s 到下一分钟..."
                )
                time.sleep(sleep_seconds)
                # 重置计数
                self._call_count_per_minute.clear()
                current_minute = int(time.time() / 60)
                self._call_count_per_minute[current_minute] = 0

            self._call_count_per_minute[current_minute] += 1

    def _call_api(self, method_name: str, **params) -> Optional[pd.DataFrame]:
        """
        统一的 Tushare API 调用入口，内置限流。

        :param method_name: Tushare API 方法名 (如 'daily', 'stock_basic')
        :param params: API 参数
        :return: DataFrame 或 None
        """
        self._enforce_rate_limit()
        try:
            def _invoke() -> Optional[pd.DataFrame]:
                pro = self._get_pro()
                func = getattr(pro, method_name)
                return func(**params)

            df = execute_with_proxy_retry(
                "Tushare",
                method_name,
                _invoke,
                max_attempts=2,
                backoff_seconds=1.0,
            )
            return df
        except Exception as e:
            logger.warning(
                f"[TushareFetcher] {method_name}() 调用失败: {e}"
            )
            return None

    def _ts_code(self, stock_code: str) -> str:
        """转换为 Tushare ts_code 格式: 600519 → 600519.SH"""
        code = normalize_stock_code(stock_code)
        if code.startswith(("6", "9")) and not code.startswith("92"):
            return f"{code}.SH"
        elif code.startswith(("0", "3")):
            return f"{code}.SZ"
        elif code.startswith(("4", "8", "92")):
            return f"{code}.BJ"
        return f"{code}.SZ"

    # ---- 日K线 (必须实现) ----

    def _fetch_raw_data(
        self,
        stock_code: str,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        """
        通过 Tushare Pro 获取日K线数据。

        pro.daily(ts_code, start_date, end_date)
        """
        ts_code = self._ts_code(stock_code)
        sd = start_date.replace("-", "")
        ed = end_date.replace("-", "")

        logger.info(
            f"[TushareFetcher] pro.daily"
            f"(ts_code={ts_code}, start_date={sd}, end_date={ed})"
        )

        df = self._call_api(
            "daily",
            ts_code=ts_code,
            start_date=sd,
            end_date=ed,
        )

        if df is not None and not df.empty:
            logger.info(f"[TushareFetcher] daily 成功: {len(df)} 行")
            return df

        return pd.DataFrame()

    def _normalize_data(
        self,
        df: pd.DataFrame,
        stock_code: str,
    ) -> pd.DataFrame:
        """将 Tushare 列名映射到标准列名"""
        if df is None or df.empty:
            return pd.DataFrame(columns=STANDARD_COLUMNS)

        col_map = {
            "trade_date": "date",
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "vol": "volume",         # Tushare 用 vol
            "amount": "amount",
            "pct_chg": "pct_chg",
        }

        df = df.rename(
            columns={k: v for k, v in col_map.items() if k in df.columns}
        )

        # Tushare 日期格式: YYYYMMDD → YYYY-MM-DD
        if "date" in df.columns:
            df["date"] = df["date"].astype(str).str[:8]
            df["date"] = pd.to_datetime(df["date"], format="%Y%m%d").dt.strftime(
                "%Y-%m-%d"
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
        通过 Tushare 获取实时行情。

        注意: Tushare 实时行情接口需要一定积分权限。
        """
        ts_code = self._ts_code(stock_code)
        code = normalize_stock_code(stock_code)

        try:
            df = self._call_api(
                "realtime_quote",
                ts_code=ts_code,
            )
            if df is None or df.empty:
                return None

            r = df.iloc[0]
            return UnifiedRealtimeQuote(
                code=code,
                name=str(r.get("name", "")),
                source=RealtimeSource.TUSHARE,
                price=safe_float(r.get("price", r.get("close"))),
                change_pct=safe_float(r.get("pct_chg")),
                volume=safe_int(r.get("vol")),
                amount=safe_float(r.get("amount")),
                open_price=safe_float(r.get("open")),
                high=safe_float(r.get("high")),
                low=safe_float(r.get("low")),
                pre_close=safe_float(r.get("pre_close")),
            )
        except Exception as e:
            logger.warning(f"[TushareFetcher] 实时行情失败: {e}")
            return None

    # ---- 筹码分布 (高级权限) ----

    def get_chip_distribution(
        self,
        stock_code: str,
    ) -> Optional[ChipDistribution]:
        """
        通过 Tushare 获取筹码分布。

        pro.cyq_chips(ts_code, start_date, end_date)
        需要高级权限。

        参考 daily_stock_analysis TushareFetcher.get_chip_distribution
        """
        ts_code = self._ts_code(stock_code)
        code = normalize_stock_code(stock_code)
        today = datetime.today()
        start = (today - timedelta(days=30)).strftime("%Y%m%d")
        end = today.strftime("%Y%m%d")

        try:
            df = self._call_api(
                "cyq_chips",
                ts_code=ts_code,
                start_date=start,
                end_date=end,
            )
            if df is None or df.empty:
                return None

            # 取最新一天的数据
            latest = df.iloc[0]
            return ChipDistribution(
                code=code,
                date=str(latest.get("trade_date", today.strftime("%Y%m%d"))),
                source="tushare",
                profit_ratio=safe_float(latest.get("his_low_pct", 0)) or 0.0,
                avg_cost=safe_float(latest.get("his_low_price", 0)) or 0.0,
                cost_90_low=safe_float(latest.get("cost_5pct", 0)) or 0.0,
                cost_90_high=safe_float(latest.get("cost_95pct", 0)) or 0.0,
                cost_70_low=safe_float(latest.get("cost_15pct", 0)) or 0.0,
                cost_70_high=safe_float(latest.get("cost_85pct", 0)) or 0.0,
            )
        except Exception as e:
            logger.warning(f"[TushareFetcher] 筹码分布获取失败: {e}")
            return None

    # ---- 股票列表 ----

    def get_stock_list(self) -> Optional[pd.DataFrame]:
        """获取股票列表"""
        df = self._call_api(
            "stock_basic",
            exchange="",
            list_status="L",
            fields="ts_code,symbol,name,area,industry,market,list_date",
        )
        return df

    # ---- 股票名称 ----

    def get_stock_name(self, stock_code: str) -> Optional[str]:
        """通过 stock_basic 获取股票名称"""
        ts_code = self._ts_code(stock_code)
        df = self._call_api(
            "stock_basic",
            ts_code=ts_code,
            fields="ts_code,name",
        )
        if df is not None and not df.empty:
            return str(df.iloc[0].get("name", ""))
        return None

    # ---- 资源释放 ----

    def close(self) -> None:
        """释放 Tushare 资源"""
        self._pro = None
        self._ts = None
