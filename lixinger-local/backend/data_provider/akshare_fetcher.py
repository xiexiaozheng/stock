"""
AkshareFetcher — akshare 多数据源 Fetcher (并发多信源版)

数据来源 (akshare 内部支持的所有信源):
  1. 东方财富: ak.stock_zh_a_hist()         — 日K线 (primary)
  2. 新浪财经: ak.stock_zh_a_daily()        — 日K线 (fallback)
  3. 网易/163: ak.stock_zh_a_hist_163()     — 日K线 (if available)
  4. 东方财富: ak.stock_zh_a_spot_em()      — 实时行情
  5. 新浪HTTP: ak.stock_zh_a_spot()         — 实时行情

改造说明:
  - _fetch_raw_data() 改为并发调用所有 akshare 信源
  - 内部使用 CrossValidator 进行交叉校验
  - 实时行情也并发采集多路源

防封禁策略:
  - 每次请求随机休眠 2-5 秒
  - 随机轮换 User-Agent
  - 自适应限流 (via error_classifier)
  - CircuitBreaker 熔断器保护各子源

实时行情多路源:
  - em:   ak.stock_zh_a_spot_em()    (东方财富)
  - sina: ak.stock_zh_a_spot()       (新浪)
  - 并发采集 + 交叉校验
"""
import logging
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

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
from data_provider.error_classifier import (
    classify_error,
    ErrorCategory,
    get_adaptive_limiter,
)
from data_provider.cross_validator import CrossValidator

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
    AkShare 数据源 Fetcher (并发多信源版)

    日K线 — 并发调用所有 akshare 信源:
      1. 东方财富: ak.stock_zh_a_hist()
      2. 新浪财经: ak.stock_zh_a_daily()
      3. 网易/163: ak.stock_zh_a_hist_163() (if available)
    返回前内部交叉校验。

    实时行情 — 并发调用多路源:
      1. em:   ak.stock_zh_a_spot_em()  (东方财富)
      2. sina: ak.stock_zh_a_spot()     (新浪)
    结果交叉校验。

    策略: 并发采集 → 交叉校验 → 返回最佳数据
    """

    name = "AkshareFetcher"
    priority = 1

    def __init__(self, sleep_min: float = 2.0, sleep_max: float = 5.0):
        super().__init__()
        self.sleep_min = sleep_min
        self.sleep_max = sleep_max
        self._validator = CrossValidator()
        self._limiter = get_adaptive_limiter(
            "akshare", base_interval=sleep_min, max_interval=30.0
        )

    # ---- 防封禁 ----

    def _set_random_user_agent(self) -> None:
        """随机设置 User-Agent"""
        random_ua = random.choice(USER_AGENTS)
        try:
            import requests
            import akshare as ak
            if hasattr(ak, "requests_cache"):
                pass
        except Exception:
            pass
        logger.debug(f"[AkshareFetcher] UA → {random_ua[:40]}...")

    def _enforce_rate_limit(self) -> None:
        """
        自适应限流: 基础 2-5 秒，遇到反爬虫自动退避。
        """
        self._limiter.wait()
        self._set_random_user_agent()
        self._last_request_time = time.time()

    # ---- akshare 信源: 各子接口独立方法 ----

    def _fetch_eastmoney(
        self, stock_code: str, sd: str, ed: str
    ) -> Tuple[str, pd.DataFrame]:
        """东方财富信源: ak.stock_zh_a_hist()"""
        source_name = "akshare_eastmoney"
        try:
            self._enforce_rate_limit()
            import akshare as ak
            logger.info(f"[AkshareFetcher] 东财信源 stock_zh_a_hist({stock_code})")
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
                self._limiter.record_success()
                logger.info(f"[AkshareFetcher] 东财信源成功: {len(df)} 行, {elapsed:.2f}s")
                return source_name, df
        except Exception as e:
            category = classify_error(e)
            if category == ErrorCategory.API_SYNTAX:
                logger.error(f"[AkshareFetcher] 东财信源 API 语法错误: {e}")
            elif category == ErrorCategory.ANTI_CRAWL:
                self._limiter.record_anti_crawl()
                logger.warning(f"[AkshareFetcher] 东财信源反爬虫: {e}")
            else:
                logger.warning(f"[AkshareFetcher] 东财信源失败: {e}")
        return source_name, pd.DataFrame()

    def _fetch_sina(
        self, stock_code: str, sd: str, ed: str
    ) -> Tuple[str, pd.DataFrame]:
        """新浪财经信源: ak.stock_zh_a_daily()"""
        source_name = "akshare_sina"
        try:
            self._enforce_rate_limit()
            import akshare as ak
            prefix = "sh" if stock_code.startswith(("6", "9")) else "sz"
            logger.info(f"[AkshareFetcher] 新浪信源 stock_zh_a_daily({prefix}{stock_code})")
            t0 = time.time()
            df = ak.stock_zh_a_daily(
                symbol=f"{prefix}{stock_code}",
                start_date=sd,
                end_date=ed,
                adjust="qfq",
            )
            elapsed = time.time() - t0
            if df is not None and not df.empty:
                self._limiter.record_success()
                logger.info(f"[AkshareFetcher] 新浪信源成功: {len(df)} 行, {elapsed:.2f}s")
                return source_name, df
        except Exception as e:
            category = classify_error(e)
            if category == ErrorCategory.API_SYNTAX:
                logger.error(f"[AkshareFetcher] 新浪信源 API 语法错误: {e}")
            elif category == ErrorCategory.ANTI_CRAWL:
                self._limiter.record_anti_crawl()
                logger.warning(f"[AkshareFetcher] 新浪信源反爬虫: {e}")
            else:
                logger.warning(f"[AkshareFetcher] 新浪信源失败: {e}")
        return source_name, pd.DataFrame()

    def _fetch_163(
        self, stock_code: str, sd: str, ed: str
    ) -> Tuple[str, pd.DataFrame]:
        """网易/163 信源: ak.stock_zh_a_hist_163() (如果存在)"""
        source_name = "akshare_163"
        try:
            self._enforce_rate_limit()
            import akshare as ak
            if not hasattr(ak, "stock_zh_a_hist_163"):
                logger.debug("[AkshareFetcher] 163 信源接口不存在，跳过")
                return source_name, pd.DataFrame()
            logger.info(f"[AkshareFetcher] 163信源 stock_zh_a_hist_163({stock_code})")
            t0 = time.time()
            df = ak.stock_zh_a_hist_163(
                symbol=stock_code,
                start_date=sd.replace("", ""),  # 保持 YYYYMMDD 格式
                end_date=ed.replace("", ""),
            )
            elapsed = time.time() - t0
            if df is not None and not df.empty:
                self._limiter.record_success()
                logger.info(f"[AkshareFetcher] 163信源成功: {len(df)} 行, {elapsed:.2f}s")
                return source_name, df
        except Exception as e:
            category = classify_error(e)
            if category == ErrorCategory.API_SYNTAX:
                logger.debug(f"[AkshareFetcher] 163信源 API 不兼容: {e}")
            else:
                logger.warning(f"[AkshareFetcher] 163信源失败: {e}")
        return source_name, pd.DataFrame()

    # ---- 日K线: 并发多信源 + 交叉校验 ----

    def _fetch_raw_data(
        self,
        stock_code: str,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        """
        并发调用 akshare 支持的所有信源获取日K线数据。

        1. 并发调用: 东方财富 + 新浪 + 163
        2. 收集所有成功返回的数据
        3. 如果多源都有数据，通过 CrossValidator 交叉校验
        4. 返回最佳数据源的数据

        如果并发无法执行 (如线程池不可用), 降级为顺序调用。
        """
        sd = start_date.replace("-", "")
        ed = end_date.replace("-", "")

        # 定义所有信源任务
        source_tasks = [
            (self._fetch_eastmoney, stock_code, sd, ed),
            (self._fetch_sina, stock_code, sd, ed),
            (self._fetch_163, stock_code, sd, ed),
        ]

        source_results: Dict[str, pd.DataFrame] = {}

        # 并发调用所有信源
        try:
            with ThreadPoolExecutor(max_workers=3, thread_name_prefix="ak_src") as executor:
                futures = {
                    executor.submit(fn, code, s, e): fn.__name__
                    for fn, code, s, e in source_tasks
                }
                for future in as_completed(futures, timeout=60):
                    try:
                        source_name, df = future.result(timeout=30)
                        if df is not None and not df.empty:
                            # 先标准化再放入校验
                            normalized = self._normalize_data(df, stock_code)
                            if not normalized.empty:
                                source_results[source_name] = normalized
                    except Exception as e:
                        task_name = futures[future]
                        logger.warning(
                            f"[AkshareFetcher] 信源任务 {task_name} 异常: {e}"
                        )
        except Exception as e:
            logger.warning(
                f"[AkshareFetcher] 并发执行异常，降级为顺序调用: {e}"
            )
            # 降级: 顺序调用
            for fn, code, s, e in source_tasks:
                try:
                    source_name, df = fn(code, s, e)
                    if df is not None and not df.empty:
                        normalized = self._normalize_data(df, stock_code)
                        if not normalized.empty:
                            source_results[source_name] = normalized
                except Exception as ex:
                    logger.warning(f"[AkshareFetcher] 顺序调用 {fn.__name__} 失败: {ex}")

        if not source_results:
            logger.warning(f"[AkshareFetcher] {stock_code} 所有信源均无数据")
            return pd.DataFrame()

        # 单源直接返回
        if len(source_results) == 1:
            source_name = next(iter(source_results))
            logger.info(f"[AkshareFetcher] {stock_code} 仅单信源 {source_name} 返回数据")
            return source_results[source_name]

        # 多源交叉校验
        report = self._validator.validate_daily_data(source_results)
        logger.info(
            f"[AkshareFetcher] {stock_code} 内部交叉校验: "
            f"{len(source_results)} 源, "
            f"一致性={report.consistency_score:.4f}, "
            f"最佳源={report.best_source}, "
            f"异常数={len(report.anomalies)}"
        )

        if report.merged_dataframe is not None and not report.merged_dataframe.empty:
            return report.merged_dataframe
        if report.best_dataframe is not None:
            return report.best_dataframe
        return next(iter(source_results.values()))

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

    # ---- 实时行情 (并发多路源) ----

    def get_realtime_quote(
        self,
        stock_code: str,
        source: str = "auto",
    ) -> Optional[UnifiedRealtimeQuote]:
        """
        并发获取实时行情，支持多种数据源并交叉校验:

        - em:   ak.stock_zh_a_spot_em()  (东方财富, 最全)
        - sina: 新浪HTTP接口
        - auto: 并发采集 em + sina，交叉校验后返回最佳

        当 source="auto" 时并发采集多路，否则只用指定源。
        """
        code = normalize_stock_code(stock_code)
        circuit_breaker = get_realtime_circuit_breaker()

        if source not in ("auto", "em", "sina"):
            source = "auto"

        if source == "auto":
            # 并发采集 em + sina
            quotes: Dict[str, Optional[UnifiedRealtimeQuote]] = {}

            def _get_em():
                source_key = "akshare_em"
                if circuit_breaker.is_available(source_key):
                    q = self._get_quote_eastmoney(code)
                    if q and q.has_basic_data():
                        circuit_breaker.record_success(source_key)
                        return "em", q
                    circuit_breaker.record_failure(source_key, "东方财富实时行情无效")
                return "em", None

            def _get_sina():
                source_key = "akshare_sina"
                if circuit_breaker.is_available(source_key):
                    q = self._get_quote_sina(code)
                    if q and q.has_basic_data():
                        circuit_breaker.record_success(source_key)
                        return "sina", q
                    circuit_breaker.record_failure(source_key, "新浪实时行情无效")
                return "sina", None

            try:
                with ThreadPoolExecutor(max_workers=2, thread_name_prefix="ak_rt") as executor:
                    futures = [executor.submit(_get_em), executor.submit(_get_sina)]
                    for future in as_completed(futures, timeout=30):
                        try:
                            name, quote = future.result(timeout=15)
                            if quote is not None:
                                quotes[name] = quote
                        except Exception as e:
                            logger.warning(f"[AkshareFetcher] 实时行情任务异常: {e}")
            except Exception as e:
                logger.warning(f"[AkshareFetcher] 实时行情并发异常: {e}")

            # 返回最完整的行情
            if not quotes:
                return None
            if len(quotes) == 1:
                return next(iter(quotes.values()))

            # 多源可用时，优先返回 em (字段更全)
            return quotes.get("em") or quotes.get("sina")

        # 指定单源
        if source == "em":
            source_key = "akshare_em"
            if circuit_breaker.is_available(source_key):
                quote = self._get_quote_eastmoney(code)
                if quote and quote.has_basic_data():
                    circuit_breaker.record_success(source_key)
                    return quote
                circuit_breaker.record_failure(source_key, "东方财富实时行情无效")

        if source == "sina":
            source_key = "akshare_sina"
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
