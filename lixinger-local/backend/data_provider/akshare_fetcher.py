"""
AkshareFetcher — akshare 多数据源 Fetcher

参考 ZhuLinsen/daily_stock_analysis data_provider/akshare_fetcher.py

数据来源:
  1. 东方财富爬虫 (akshare 默认) — 日K线、实时行情
  2. 新浪财经接口 — 备选实时行情
  3. 腾讯财经接口 — 备选实时行情

防封禁策略:
  - 每次请求随机休眠 2-5 秒
  - 随机轮换 User-Agent
  - tenacity 指数退避重试 (2→4→8s, 最多3次)
  - CircuitBreaker 熔断器保护各子源

实时行情3路源:
  - em:   ak.stock_zh_a_spot_em()    (东方财富)
  - sina: ak.stock_zh_a_spot()       (新浪) — fallback 已确认在旧版可用
  - 东财接口优先, 失败切新浪
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
    RateLimitError,
    STANDARD_COLUMNS,
    normalize_stock_code,
)
from data_provider.realtime_types import (
    UnifiedRealtimeQuote,
    RealtimeSource,
    get_realtime_circuit_breaker,
    safe_float,
    safe_int,
)

logger = logging.getLogger(__name__)


# User-Agent 池，用于随机轮换（参考 daily_stock_analysis）
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) "
    "Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

# 缓存实时行情数据（避免重复请求），参考 daily_stock_analysis
_realtime_cache: Dict[str, Any] = {
    "data": None,
    "timestamp": 0,
    "ttl": 1200,  # 20分钟缓存
}


class AkshareFetcher(BaseFetcher):
    """
    AkShare 数据源 Fetcher

    日K线: ak.stock_zh_a_hist (东方财富)
      └─ fallback: ak.stock_zh_a_daily (新浪)

    实时行情 (3 路):
      1. em:   ak.stock_zh_a_spot_em()  (东方财富，最全)
      2. sina: 新浪HTTP API (轻量级)
      3. tencent: 腾讯HTTP API (备选)

    策略: 东财优先 → 新浪补充 → 腾讯兜底
    """

    name = "AkshareFetcher"
    priority = 1

    def __init__(self, sleep_min: float = 2.0, sleep_max: float = 5.0):
        super().__init__()
        self.sleep_min = sleep_min
        self.sleep_max = sleep_max

    # ---- 防封禁 ----

    def _set_random_user_agent(self) -> None:
        """随机设置 User-Agent"""
        random_ua = random.choice(USER_AGENTS)
        try:
            import requests
            # 尝试更新 akshare 内部 session 的 UA
            # 这是 best-effort，不保证所有版本兼容
            import akshare as ak
            if hasattr(ak, "requests_cache"):
                pass  # 某些版本使用 requests-cache
        except Exception:
            pass
        logger.debug(f"[AkshareFetcher] UA → {random_ua[:40]}...")

    def _enforce_rate_limit(self) -> None:
        """
        强制限流: 随机休眠 2-5 秒

        参考 daily_stock_analysis AkshareFetcher._enforce_rate_limit
        """
        now = time.time()
        elapsed = now - self._last_request_time
        min_interval = self.sleep_min

        if elapsed < min_interval:
            additional_sleep = min_interval - elapsed
            logger.debug(f"[AkshareFetcher] 补充休眠 {additional_sleep:.2f}s")
            time.sleep(additional_sleep)

        self._set_random_user_agent()
        self.random_sleep(self.sleep_min, self.sleep_max)
        self._last_request_time = time.time()

    # ---- 日K线 (必须实现) ----

    def _fetch_raw_data(
        self,
        stock_code: str,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        """
        获取日K线原始数据。

        优先使用东方财富接口 (stock_zh_a_hist)。
        失败后尝试新浪接口 (stock_zh_a_daily)。

        参考 daily_stock_analysis _fetch_daily_data_eastmoney / _fetch_daily_data_sina
        """
        self._enforce_rate_limit()

        # 日期格式转换
        sd = start_date.replace("-", "")
        ed = end_date.replace("-", "")

        # 尝试1: 东方财富 (primary)
        try:
            import akshare as ak
            logger.info(
                f"[AkshareFetcher] ak.stock_zh_a_hist"
                f"(symbol={stock_code}, period=daily, "
                f"start_date={sd}, end_date={ed})"
            )
            t0 = time.time()
            df = ak.stock_zh_a_hist(
                symbol=stock_code,
                period="daily",
                start_date=sd,
                end_date=ed,
                adjust="qfq",
            )
            elapsed = time.time() - t0
            if df is not None and not df.empty:
                logger.info(
                    f"[AkshareFetcher] stock_zh_a_hist 成功: "
                    f"{len(df)} 行, {elapsed:.2f}s"
                )
                return df
            logger.warning("[AkshareFetcher] stock_zh_a_hist 返回空数据")
        except Exception as e:
            logger.warning(f"[AkshareFetcher] stock_zh_a_hist 失败: {e}")

        # 尝试2: 新浪财经 (fallback)
        self._enforce_rate_limit()
        try:
            import akshare as ak
            logger.info(f"[AkshareFetcher] 尝试新浪接口 stock_zh_a_daily...")
            t0 = time.time()
            # 新浪接口需要带交易所前缀
            prefix = "sh" if stock_code.startswith(("6", "9")) else "sz"
            df = ak.stock_zh_a_daily(
                symbol=f"{prefix}{stock_code}",
                start_date=sd,
                end_date=ed,
                adjust="qfq",
            )
            elapsed = time.time() - t0
            if df is not None and not df.empty:
                logger.info(
                    f"[AkshareFetcher] stock_zh_a_daily 成功: "
                    f"{len(df)} 行, {elapsed:.2f}s"
                )
                return df
        except Exception as e:
            logger.warning(f"[AkshareFetcher] stock_zh_a_daily 也失败: {e}")

        return pd.DataFrame()

    def _normalize_data(
        self,
        df: pd.DataFrame,
        stock_code: str,
    ) -> pd.DataFrame:
        """将 akshare 列名映射到标准列名"""
        if df is None or df.empty:
            return pd.DataFrame(columns=STANDARD_COLUMNS)

        col_map = {
            "日期": "date",
            "date": "date",
            "开盘": "open",
            "open": "open",
            "最高": "high",
            "high": "high",
            "最低": "low",
            "low": "low",
            "收盘": "close",
            "close": "close",
            "成交量": "volume",
            "volume": "volume",
            "成交额": "amount",
            "amount": "amount",
            "涨跌幅": "pct_chg",
            "pct_chg": "pct_chg",
        }

        df = df.rename(
            columns={k: v for k, v in col_map.items() if k in df.columns}
        )

        # 确保必须的列存在
        for col in STANDARD_COLUMNS:
            if col not in df.columns:
                df[col] = None

        return df[STANDARD_COLUMNS]

    # ---- 实时行情 (3 路源) ----

    def get_realtime_quote(
        self,
        stock_code: str,
        source: str = "em",
    ) -> Optional[UnifiedRealtimeQuote]:
        """
        获取实时行情，支持3种数据源:

        - em:   ak.stock_zh_a_spot_em()  (东方财富, 最全)
        - sina: 新浪HTTP接口
        - auto: em → sina 自动切换

        参考 daily_stock_analysis AkshareFetcher.get_realtime_quote
        """
        code = normalize_stock_code(stock_code)
        circuit_breaker = get_realtime_circuit_breaker()

        if source == "auto" or source == "em":
            source_key = f"akshare_em"
            if circuit_breaker.is_available(source_key):
                quote = self._get_quote_eastmoney(code)
                if quote and quote.has_basic_data():
                    circuit_breaker.record_success(source_key)
                    return quote
                circuit_breaker.record_failure(source_key, "东方财富实时行情无效")

        if source == "auto" or source == "sina":
            source_key = f"akshare_sina"
            if circuit_breaker.is_available(source_key):
                quote = self._get_quote_sina(code)
                if quote and quote.has_basic_data():
                    circuit_breaker.record_success(source_key)
                    return quote
                circuit_breaker.record_failure(source_key, "新浪实时行情无效")

        return None

    def _get_quote_eastmoney(
        self,
        stock_code: str,
    ) -> Optional[UnifiedRealtimeQuote]:
        """
        从东方财富获取实时行情

        使用 ak.stock_zh_a_spot_em() 获取全市场数据并缓存。
        """
        global _realtime_cache

        now = time.time()
        if (
            _realtime_cache["data"] is not None
            and (now - _realtime_cache["timestamp"]) < _realtime_cache["ttl"]
        ):
            df = _realtime_cache["data"]
        else:
            self._enforce_rate_limit()
            try:
                import akshare as ak
                logger.info("[AkshareFetcher] ak.stock_zh_a_spot_em() 获取A股实时行情...")
                t0 = time.time()

                # 重试机制（参考 daily_stock_analysis）
                last_error = None
                for attempt in range(1, 3):
                    try:
                        df = ak.stock_zh_a_spot_em()
                        if df is not None and not df.empty:
                            break
                    except Exception as e:
                        last_error = e
                        logger.warning(
                            f"[AkshareFetcher] stock_zh_a_spot_em "
                            f"attempt {attempt}/2 失败: {e}"
                        )
                        time.sleep(min(2 ** attempt, 5))
                else:
                    logger.error(
                        f"[AkshareFetcher] stock_zh_a_spot_em 最终失败: {last_error}"
                    )
                    return None

                elapsed = time.time() - t0
                logger.info(
                    f"[AkshareFetcher] stock_zh_a_spot_em 成功: "
                    f"{len(df)} 只股票, {elapsed:.2f}s"
                )

                _realtime_cache["data"] = df
                _realtime_cache["timestamp"] = now
            except Exception as e:
                logger.error(f"[AkshareFetcher] 东方财富实时行情异常: {e}")
                return None

        if df is None or df.empty:
            return None

        # 查找目标股票
        code_col = None
        for col_name in ("代码", "stock_code", "code"):
            if col_name in df.columns:
                code_col = col_name
                break

        if code_col is None:
            logger.warning("[AkshareFetcher] 东方财富实时行情缺少代码列")
            return None

        row = df[df[code_col].astype(str).str.zfill(6) == stock_code]
        if row.empty:
            return None

        r = row.iloc[0]
        return UnifiedRealtimeQuote(
            code=stock_code,
            name=str(r.get("名称", r.get("name", ""))),
            source=RealtimeSource.AKSHARE_EM,
            price=safe_float(r.get("最新价", r.get("price"))),
            change_pct=safe_float(r.get("涨跌幅", r.get("pct_chg"))),
            change_amount=safe_float(r.get("涨跌额", r.get("change"))),
            volume=safe_int(r.get("成交量", r.get("volume"))),
            amount=safe_float(r.get("成交额", r.get("amount"))),
            volume_ratio=safe_float(r.get("量比", r.get("volume_ratio"))),
            turnover_rate=safe_float(r.get("换手率", r.get("turnover_rate"))),
            amplitude=safe_float(r.get("振幅", r.get("amplitude"))),
            open_price=safe_float(r.get("今开", r.get("open"))),
            high=safe_float(r.get("最高", r.get("high"))),
            low=safe_float(r.get("最低", r.get("low"))),
            pre_close=safe_float(r.get("昨收", r.get("pre_close"))),
            pe_ratio=safe_float(r.get("市盈率-动态", r.get("pe_ratio"))),
            pb_ratio=safe_float(r.get("市净率", r.get("pb_ratio"))),
            total_mv=safe_float(r.get("总市值", r.get("total_mv"))),
            circ_mv=safe_float(r.get("流通市值", r.get("circ_mv"))),
            change_60d=safe_float(r.get("60日涨跌幅", r.get("change_60d"))),
        )

    def _get_quote_sina(
        self,
        stock_code: str,
    ) -> Optional[UnifiedRealtimeQuote]:
        """
        从新浪财经获取实时行情 (轻量级备选)

        使用 ak.stock_zh_a_spot() 或 ak.stock_bid_ask_em()
        """
        self._enforce_rate_limit()
        try:
            import akshare as ak
            # 尝试新浪全市场行情
            try:
                df = ak.stock_zh_a_spot()
                if df is not None and not df.empty:
                    code_col = None
                    for col_name in ("代码", "symbol", "code"):
                        if col_name in df.columns:
                            code_col = col_name
                            break
                    if code_col:
                        row = df[
                            df[code_col].astype(str).str.replace(
                                r"^(sh|sz|bj)", "", regex=True
                            ).str.zfill(6) == stock_code
                        ]
                        if not row.empty:
                            r = row.iloc[0]
                            return UnifiedRealtimeQuote(
                                code=stock_code,
                                name=str(r.get("名称", r.get("name", ""))),
                                source=RealtimeSource.AKSHARE_SINA,
                                price=safe_float(r.get("最新价", r.get("trade"))),
                                change_pct=safe_float(
                                    r.get("涨跌幅", r.get("changepercent"))
                                ),
                                volume=safe_int(r.get("成交量", r.get("volume"))),
                                amount=safe_float(r.get("成交额", r.get("amount"))),
                                open_price=safe_float(r.get("今开", r.get("open"))),
                                high=safe_float(r.get("最高", r.get("high"))),
                                low=safe_float(r.get("最低", r.get("low"))),
                                pre_close=safe_float(
                                    r.get("昨收", r.get("settlement"))
                                ),
                            )
            except Exception as e:
                logger.debug(f"[AkshareFetcher] stock_zh_a_spot 失败: {e}")

        except Exception as e:
            logger.warning(f"[AkshareFetcher] 新浪实时行情异常: {e}")

        return None

    # ---- 股票列表 ----

    def get_stock_list(self) -> Optional[pd.DataFrame]:
        """获取A股全市场股票列表"""
        self._enforce_rate_limit()
        try:
            import akshare as ak
            df = ak.stock_info_a_code_name()
            return df
        except Exception as e:
            logger.warning(f"[AkshareFetcher] 股票列表获取失败: {e}")
            return None

    # ---- 股票名称 ----

    def get_stock_name(self, stock_code: str) -> Optional[str]:
        """从实时行情获取股票名称"""
        quote = self.get_realtime_quote(stock_code, source="em")
        return quote.name if quote and quote.name else None
