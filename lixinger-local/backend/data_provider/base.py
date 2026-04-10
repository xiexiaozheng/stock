"""
多数据源 Fetcher 基类与 Manager (并发多源 + 交叉校验版)

BaseFetcher: 所有数据源实现的抽象基类
  - _fetch_raw_data() / _normalize_data(): 子类必须实现
  - get_daily_data(): 统一入口 (fetch → normalize → clean → indicators)
  - get_realtime_quote(): 可选实现
  - 内置 random_sleep, _clean_data, _calculate_indicators

DataFetcherManager: 策略管理器
  - 支持并发多源获取 (get_daily_data_concurrent)
  - 多数据源交叉校验 (CrossValidator)
  - 汇总可用/失败诊断
  - 多数据源字段补充
  - 线程安全

改造说明:
  - get_daily_data_concurrent(): 并发调用所有可用 Fetcher
  - get_daily_data() 保留兼容参数但统一走并发入口
  - 注册新数据源: YFinance, Longbridge, Eastmoney
  - 使用 error_classifier 智能分类错误
"""
import importlib
import importlib.util
import logging
import os
import random
import threading
import time
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from data_provider.realtime_types import (
    UnifiedRealtimeQuote,
    ChipDistribution,
    RealtimeSource,
    get_realtime_circuit_breaker,
    get_daily_circuit_breaker,
    merge_quote_fields,
    safe_float,
)
from data_provider.source_config import (
    build_unavailable_reason,
    get_framework_configs,
)
from utils.api_compat import call_akshare

logger = logging.getLogger(__name__)

# 标准化列名 — 所有 Fetcher 输出必须包含这些列
STANDARD_COLUMNS = ["date", "open", "high", "low", "close", "volume", "amount", "pct_chg"]


# =====================================================================
# 启动诊断
# =====================================================================

@dataclass
class FetcherStartupStatus:
    """
    记录单个 Fetcher 的启动状态。

    用于暴露"哪些框架初始化成功、哪些失败及原因"，
    使调用方无需猜测某个数据源是否参与了本次请求。
    """
    framework_key: str
    """框架唯一标识 (e.g. 'akshare')"""

    name: str
    """Fetcher 名称 (e.g. 'TushareFetcher')"""

    available: bool
    """是否成功注册"""

    failure_reason: Optional[str] = None
    """注册失败时的原因描述"""

    capabilities: List[str] = field(default_factory=list)
    """框架支持能力"""

    def __str__(self) -> str:
        if self.available:
            return f"  ✅ {self.name} (enabled)"
        reason = self.failure_reason or "unknown reason"
        if "unavailable:" in reason:
            return f"  ❌ {self.name} ({reason})"
        return f"  ❌ {self.name} (unavailable: {reason})"
# 异常层次
# =====================================================================

class DataFetchError(Exception):
    """数据获取基础异常"""
    pass


class RateLimitError(DataFetchError):
    """API 速率限制异常"""
    pass


class DataSourceUnavailableError(DataFetchError):
    """数据源暂时不可用"""
    pass


# =====================================================================
# 代码工具函数
# =====================================================================

def normalize_stock_code(code: str) -> str:
    """
    标准化股票代码为6位纯数字。

    'SH600519' → '600519'
    '000001.SZ' → '000001'
    '600519' → '600519'
    """
    code = str(code).strip().upper()
    # 去除交易所前缀
    for prefix in ("SH", "SZ", "BJ"):
        if code.startswith(prefix):
            code = code[len(prefix):]
    # 去除交易所后缀
    if "." in code:
        code = code.split(".")[0]
    return code.zfill(6)


def is_bse_code(code: str) -> bool:
    """判断是否为北交所代码"""
    c = normalize_stock_code(code)
    return c.startswith(("43", "83", "87", "88", "92"))


def is_st_stock(name: str) -> bool:
    """判断是否为 ST / *ST 股票 (涨跌幅 5%)"""
    name_upper = str(name).strip().upper()
    return "ST" in name_upper


def is_kc_cy_stock(code: str) -> bool:
    """判断是否为科创板 (688xx) 或创业板 (30xx) — 涨跌幅 20%"""
    c = normalize_stock_code(code)
    return c.startswith(("688", "30"))


# =====================================================================
# BaseFetcher
# =====================================================================

class BaseFetcher(ABC):
    """
    数据源 Fetcher 抽象基类

    所有数据源（akshare/efinance/baostock/tushare）必须继承此类。

    子类必须实现:
      - name: str          数据源名称
      - _fetch_raw_data()  从数据源获取原始 DataFrame
      - _normalize_data()  将原始列名映射到 STANDARD_COLUMNS

    子类可选覆盖:
      - get_realtime_quote()   实时行情
      - get_stock_name()       股票名称
      - get_stock_list()       股票列表
      - get_chip_distribution() 筹码分布
      - close()                释放资源
    """

    name: str = "BaseFetcher"
    framework_key: str = "base"

    def __init__(self):
        self._last_request_time: float = 0.0

    # ---- 子类必须实现 ----

    @abstractmethod
    def _fetch_raw_data(
        self,
        stock_code: str,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        """
        从数据源获取原始 K 线数据。

        :param stock_code: 6位纯数字股票代码
        :param start_date: 开始日期 YYYY-MM-DD
        :param end_date: 结束日期 YYYY-MM-DD
        :return: 原始 DataFrame
        """
        ...

    @abstractmethod
    def _normalize_data(
        self,
        df: pd.DataFrame,
        stock_code: str,
    ) -> pd.DataFrame:
        """
        将原始 DataFrame 列名映射到 STANDARD_COLUMNS。

        :return: 列名为 STANDARD_COLUMNS 的 DataFrame
        """
        ...

    # ---- 公共入口 ----

    def get_daily_data(
        self,
        stock_code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        days: int = 30,
    ) -> pd.DataFrame:
        """
        获取日 K 线数据的统一入口。

        流程:
        1. 计算日期范围
        2. 调用 _fetch_raw_data()（子类实现）
        3. 调用 _normalize_data()（标准化列名）
        4. _clean_data()（清洗、排序、类型转换）
        5. _calculate_indicators()（MA5/10/20、量比）
        """
        code = normalize_stock_code(stock_code)
        if end_date is None:
            end_date = datetime.today().strftime("%Y-%m-%d")
        if start_date is None:
            start_dt = datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=days * 2)
            start_date = start_dt.strftime("%Y-%m-%d")

        logger.debug(
            f"[{self.name}] get_daily_data: code={code}, "
            f"{start_date} → {end_date}"
        )

        raw_df = self._fetch_raw_data(code, start_date, end_date)
        if raw_df is None or raw_df.empty:
            return pd.DataFrame(columns=STANDARD_COLUMNS)

        normalized = self._normalize_data(raw_df, code)
        cleaned = self._clean_data(normalized)
        with_indicators = self._calculate_indicators(cleaned)

        # 按日期范围截取
        if not with_indicators.empty and "date" in with_indicators.columns:
            filtered = with_indicators[with_indicators["date"] >= start_date]
            if days and days > 0:
                filtered = filtered.tail(days)
            with_indicators = filtered

        return with_indicators

    # ---- 可选覆盖 ----

    def get_realtime_quote(
        self,
        stock_code: str,
        source: str = "default",
    ) -> Optional[UnifiedRealtimeQuote]:
        """获取实时行情，默认不支持"""
        return None

    def get_stock_name(self, stock_code: str) -> Optional[str]:
        """获取股票名称"""
        return None

    def get_stock_list(self) -> Optional[pd.DataFrame]:
        """获取股票列表"""
        return None

    def get_chip_distribution(self, stock_code: str) -> Optional[ChipDistribution]:
        """获取筹码分布"""
        return None

    def close(self) -> None:
        """释放数据源资源（如 baostock 登出）"""
        pass

    # ---- 内置工具 ----

    @staticmethod
    def random_sleep(min_seconds: float = 1.0, max_seconds: float = 3.0) -> None:
        """随机休眠（防封禁核心策略之一）"""
        delay = random.uniform(min_seconds, max_seconds)
        time.sleep(delay)

    @staticmethod
    def _clean_data(df: pd.DataFrame) -> pd.DataFrame:
        """
        清洗数据:
        - 去除全空行
        - 转换数值类型
        - 按日期排序
        - 去除重复行
        """
        if df is None or df.empty:
            return pd.DataFrame(columns=STANDARD_COLUMNS)

        df = df.copy()

        # 确保日期列为字符串
        if "date" in df.columns:
            df["date"] = df["date"].astype(str)

        # 数值列类型转换
        numeric_cols = ["open", "high", "low", "close", "volume", "amount", "pct_chg"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # 去除无效行（必须有日期和收盘价）
        if "date" in df.columns and "close" in df.columns:
            df = df.dropna(subset=["date", "close"])

        # 去重、排序
        if "date" in df.columns:
            df = df.drop_duplicates(subset=["date"], keep="last")
            df = df.sort_values("date").reset_index(drop=True)

        return df

    @staticmethod
    def _calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
        """
        计算常用技术指标:
        - MA5, MA10, MA20 (均线)
        - volume_ratio (量比: 当日成交量 / 5日平均)
        """
        if df is None or df.empty or "close" not in df.columns:
            return df

        df = df.copy()

        # 均线
        for period in (5, 10, 20):
            col = f"ma{period}"
            if len(df) >= period:
                df[col] = df["close"].rolling(window=period, min_periods=period).mean()
            else:
                df[col] = None

        # 量比
        if "volume" in df.columns and len(df) >= 5:
            ma_vol_5 = df["volume"].rolling(window=5, min_periods=5).mean()
            df["volume_ratio"] = df["volume"] / ma_vol_5.replace(0, float("nan"))
        else:
            df["volume_ratio"] = None

        return df


# =====================================================================
# DataFetcherManager — 多数据源编排器
# =====================================================================

class DataFetcherManager:
    """
    多数据源管理器 (并发多源 + 交叉校验版)

    统一并发调用所有可用 Fetcher，收集结果后交叉校验并输出诊断。

    管理所有 Fetcher 实例:
    - EfinanceFetcher (东方财富 efinance)
    - AkshareFetcher (akshare 多信源并发)
    - TushareFetcher (Tushare Pro)
    - BaostockFetcher (证券宝)
    - YFinanceFetcher (Yahoo Finance)
    - LongbridgeFetcher (长桥)
    - EastmoneyFetcher (东财直连)

    用法:
        manager = DataFetcherManager()
        df, source = manager.get_daily_data('600519')
        quote = manager.get_realtime_quote('600519')
        manager.close()
    """

    def __init__(self, fetchers: Optional[List[BaseFetcher]] = None):
        self._fetchers: List[BaseFetcher] = []
        self._fetchers_lock = threading.RLock()
        self._stock_name_cache: Dict[str, str] = {}
        self._stock_name_cache_lock = threading.Lock()
        # 启动诊断: 记录每个 Fetcher 的初始化状态
        self._startup_statuses: List[FetcherStartupStatus] = []
        self._last_request_diagnostics: Dict[str, Dict[str, Any]] = {}

        if fetchers:
            for f in fetchers:
                self.register_fetcher(f)
        else:
            self._auto_register_fetchers()
            # 打印启动摘要，方便排查
            self._log_startup_summary()

    def _log_startup_summary(self) -> None:
        """打印所有 Fetcher 的启动状态摘要"""
        available = [s for s in self._startup_statuses if s.available]
        unavailable = [s for s in self._startup_statuses if not s.available]
        logger.info(
            f"[DataFetcherManager] 启动完成: "
            f"{len(available)} 个数据源可用, {len(unavailable)} 个不可用"
        )
        for s in self._startup_statuses:
            if s.available:
                logger.info(str(s))
            else:
                logger.warning(str(s))

    def get_startup_status(self) -> List[FetcherStartupStatus]:
        """
        返回所有 Fetcher 的启动状态列表（包括失败的）。

        调用方可用此方法了解哪些框架可用、哪些不可用以及失败原因。

        示例::

            manager = DataFetcherManager()
            for status in manager.get_startup_status():
                print(status)
            # ✅ AkshareFetcher (enabled)
            # ❌ LongbridgeFetcher (unavailable: missing env ...)
        """
        return list(self._startup_statuses)

    def get_startup_diagnostics(self) -> Dict[str, Any]:
        return {
            "available_fetchers": [
                {
                    "framework": status.framework_key,
                    "name": status.name,
                    "capabilities": status.capabilities,
                }
                for status in self._startup_statuses
                if status.available
            ],
            "unavailable_fetchers": [
                {
                    "framework": status.framework_key,
                    "name": status.name,
                    "reason": status.failure_reason,
                }
                for status in self._startup_statuses
                if not status.available
            ],
        }

    def _auto_register_fetchers(self) -> None:
        framework_configs = get_framework_configs()
        for framework_key, framework_config in framework_configs.items():
            name = framework_config["name"]
            capabilities = list(framework_config.get("capabilities", []))
            if not framework_config.get("enabled_by_default", True):
                reason = "disabled by configuration"
                self._startup_statuses.append(
                    FetcherStartupStatus(
                        framework_key=framework_key,
                        name=name,
                        available=False,
                        failure_reason=reason,
                        capabilities=capabilities,
                    )
                )
                continue

            dependency = framework_config.get("required_dependency")
            if dependency and importlib.util.find_spec(dependency) is None:
                reason = build_unavailable_reason(
                    framework_config, f"missing dependency: {dependency}"
                )
                self._startup_statuses.append(
                    FetcherStartupStatus(
                        framework_key=framework_key,
                        name=name,
                        available=False,
                        failure_reason=reason,
                        capabilities=capabilities,
                    )
                )
                continue

            missing_env = [
                key for key in framework_config.get("required_env", [])
                if not os.getenv(key)
            ]
            if missing_env:
                reason = build_unavailable_reason(
                    framework_config, f"missing env: {', '.join(missing_env)}"
                )
                self._startup_statuses.append(
                    FetcherStartupStatus(
                        framework_key=framework_key,
                        name=name,
                        available=False,
                        failure_reason=reason,
                        capabilities=capabilities,
                    )
                )
                continue

            try:
                module_path, class_name = framework_config["fetcher_class"].rsplit(".", 1)
                fetcher_class = getattr(importlib.import_module(module_path), class_name)
                ctor_kwargs = {
                    arg_name: os.getenv(env_name, "")
                    for arg_name, env_name in framework_config.get("constructor_env", {}).items()
                }
                fetcher = fetcher_class(**ctor_kwargs)
                fetcher.framework_key = framework_key
                self.register_fetcher(fetcher)
                self._startup_statuses.append(
                    FetcherStartupStatus(
                        framework_key=framework_key,
                        name=name,
                        available=True,
                        capabilities=capabilities,
                    )
                )
                logger.info("[DataFetcherManager] 注册 %s (enabled)", name)
            except Exception as exc:
                reason = build_unavailable_reason(framework_config, str(exc))
                self._startup_statuses.append(
                    FetcherStartupStatus(
                        framework_key=framework_key,
                        name=name,
                        available=False,
                        failure_reason=reason,
                        capabilities=capabilities,
                    )
                )
                logger.warning("[DataFetcherManager] %s 不可用: %s", name, reason)

    def register_fetcher(self, fetcher: BaseFetcher) -> None:
        """注册一个 Fetcher，保持配置顺序。"""
        with self._fetchers_lock:
            self._fetchers.append(fetcher)

    def get_fetchers(self, capability: Optional[str] = None) -> List[BaseFetcher]:
        """返回 Fetcher 列表，可按 capability 过滤。"""
        with self._fetchers_lock:
            fetchers = list(self._fetchers)
        if capability is None:
            return fetchers
        capabilities_by_framework = {
            status.framework_key: set(status.capabilities)
            for status in self._startup_statuses
            if status.available
        }
        return [
            fetcher for fetcher in fetchers
            if capability in capabilities_by_framework.get(
                getattr(fetcher, "framework_key", ""), set()
            )
        ]

    # ---- 日K线数据（并发多源 + 交叉校验）----

    def get_daily_data(
        self,
        stock_code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        days: int = 30,
        concurrent: bool = True,
    ) -> Tuple[pd.DataFrame, str]:
        """
        获取日K线数据。

        :param concurrent: 兼容旧参数；当前始终并发执行
        :return: (DataFrame, source_name)
        :raises DataFetchError: 所有数据源都失败时
        """
        return self.get_daily_data_concurrent(stock_code, start_date, end_date, days)

    def get_last_request_diagnostic(self, capability: str = "daily_quotes") -> Dict[str, Any]:
        return dict(self._last_request_diagnostics.get(capability, {}))

    def get_daily_data_concurrent(
        self,
        stock_code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        days: int = 30,
    ) -> Tuple[pd.DataFrame, str]:
        """
        并发调用所有可用 Fetcher 获取日K线数据。

        流程:
        1. 并发调用所有未熔断的 Fetcher
        2. 收集所有成功返回的结果
        3. 如果多源都有数据，通过 CrossValidator 交叉校验
        4. 返回最佳数据源的数据

        :return: (DataFrame, source_info_string)
        """
        from data_provider.cross_validator import CrossValidator
        from data_provider.error_classifier import classify_error, ErrorCategory

        # 从配置获取超时值
        try:
            from config import CONCURRENT_FETCH_TIMEOUT, CONCURRENT_MAX_WORKERS
        except ImportError:
            CONCURRENT_FETCH_TIMEOUT = 120.0
            CONCURRENT_MAX_WORKERS = 7

        circuit_breaker = get_daily_circuit_breaker()
        fetchers = self.get_fetchers(capability="daily_quotes")
        errors: List[str] = []
        source_results: Dict[str, pd.DataFrame] = {}
        diagnostic = {
            "attempted_fetchers": [fetcher.name for fetcher in fetchers],
            "successful_fetchers": [],
            "failed_fetchers": [],
            "failure_reasons": {},
            "best_source": None,
            "merged_sources": [],
            "consistency_score": 0.0,
        }

        def _fetch_from_source(fetcher: BaseFetcher) -> Tuple[str, pd.DataFrame, Optional[str]]:
            """从单个数据源获取数据"""
            source_key = f"daily_{fetcher.name}"
            if not circuit_breaker.is_available(source_key):
                return fetcher.name, pd.DataFrame(), "熔断中"
            try:
                df = fetcher.get_daily_data(
                    stock_code,
                    start_date=start_date,
                    end_date=end_date,
                    days=days,
                )
                if df is not None and not df.empty:
                    circuit_breaker.record_success(source_key)
                    return fetcher.name, df, None
                circuit_breaker.record_inconclusive(source_key)
                return fetcher.name, pd.DataFrame(), "返回空数据"
            except Exception as e:
                category = classify_error(e)
                if category == ErrorCategory.API_SYNTAX:
                    logger.error(
                        f"[DataFetcherManager] {fetcher.name} API 语法错误: {e}"
                    )
                elif category == ErrorCategory.ANTI_CRAWL:
                    logger.warning(
                        f"[DataFetcherManager] {fetcher.name} 反爬虫错误: {e}"
                    )
                circuit_breaker.record_failure(source_key, str(e))
                return fetcher.name, pd.DataFrame(), f"{category.value}: {e}"

        # 并发调用所有 Fetcher
        try:
            max_workers = min(len(fetchers), CONCURRENT_MAX_WORKERS)
            with ThreadPoolExecutor(
                max_workers=max_workers,
                thread_name_prefix="daily_src",
            ) as executor:
                futures = {
                    executor.submit(_fetch_from_source, f): f.name
                    for f in fetchers
                }
                for future in as_completed(futures, timeout=CONCURRENT_FETCH_TIMEOUT):
                    try:
                        name, df, error_reason = future.result(timeout=CONCURRENT_FETCH_TIMEOUT / 2)
                        if df is not None and not df.empty:
                            source_results[name] = df
                            diagnostic["successful_fetchers"].append(name)
                        elif name:
                            errors.append(f"{name}: {error_reason or '返回空数据'}")
                            diagnostic["failed_fetchers"].append(name)
                            diagnostic["failure_reasons"][name] = error_reason or "返回空数据"
                    except Exception as e:
                        fetcher_name = futures[future]
                        errors.append(f"{fetcher_name}: {e}")
                        diagnostic["failed_fetchers"].append(fetcher_name)
                        diagnostic["failure_reasons"][fetcher_name] = str(e)
        except Exception as e:
            diagnostic["failed_fetchers"].extend(
                name for name in diagnostic["attempted_fetchers"]
                if name not in diagnostic["failed_fetchers"]
                and name not in diagnostic["successful_fetchers"]
            )
            self._last_request_diagnostics["daily_quotes"] = diagnostic
            raise DataFetchError(f"并发执行异常: {e}") from e

        if not source_results:
            self._last_request_diagnostics["daily_quotes"] = diagnostic
            raise DataFetchError(
                f"所有数据源获取 {stock_code} 日K线均失败 (并发模式):\n"
                + "\n".join(f"  - {e}" for e in errors)
            )

        # 单源直接返回
        if len(source_results) == 1:
            source_name = next(iter(source_results))
            df = source_results[source_name]
            diagnostic["best_source"] = source_name
            diagnostic["merged_sources"] = [source_name]
            diagnostic["consistency_score"] = 1.0
            self._last_request_diagnostics["daily_quotes"] = diagnostic
            logger.info(
                f"[DataFetcherManager] {stock_code} 日K线仅 {source_name} 返回 {len(df)} 行"
            )
            return df, source_name

        # 多源交叉校验
        validator = CrossValidator()
        report = validator.validate_daily_data(source_results)

        sources_info = (
            f"concurrent({len(source_results)}源: "
            f"{','.join(source_results.keys())}|"
            f"best={report.best_source}|"
            f"score={report.consistency_score:.4f})"
        )
        diagnostic["best_source"] = report.best_source
        diagnostic["merged_sources"] = list(source_results.keys())
        diagnostic["consistency_score"] = report.consistency_score
        diagnostic["anomalies"] = report.anomalies
        self._last_request_diagnostics["daily_quotes"] = diagnostic
        logger.info(
            f"[DataFetcherManager] {stock_code} 并发校验完成: {sources_info}"
        )

        # 优先使用融合数据 (中位数), 次之用最佳源
        if report.merged_dataframe is not None and not report.merged_dataframe.empty:
            return report.merged_dataframe, sources_info
        if report.best_dataframe is not None and not report.best_dataframe.empty:
            return report.best_dataframe, sources_info
        # 兜底: 返回第一个
        first_name = next(iter(source_results))
        return source_results[first_name], first_name

    def _get_daily_data_failover(
        self,
        stock_code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        days: int = 30,
    ) -> Tuple[pd.DataFrame, str]:
        """兼容旧接口，内部转到并发入口。"""
        return self.get_daily_data_concurrent(stock_code, start_date, end_date, days)

    # ---- 实时行情（多源补充）----

    def get_realtime_quote(
        self,
        stock_code: str,
    ) -> Optional[UnifiedRealtimeQuote]:
        """
        获取实时行情，尝试所有 Fetcher 并合并缺失字段。

        策略:
        1. 依次尝试已注册且可用的数据源
        2. 如果报价缺少量能/估值字段，从后续数据源补充
        3. 熔断器保护每个数据源
        """
        circuit_breaker = get_realtime_circuit_breaker()
        primary_quote: Optional[UnifiedRealtimeQuote] = None

        for fetcher in self.get_fetchers():
            source_key = f"realtime_{fetcher.name}"

            if not circuit_breaker.is_available(source_key):
                continue

            try:
                quote = fetcher.get_realtime_quote(stock_code)
                if quote is None or not quote.has_basic_data():
                    continue

                circuit_breaker.record_success(source_key)

                if primary_quote is None:
                    primary_quote = quote
                    if not primary_quote.needs_supplement():
                        return primary_quote
                else:
                    # 从后续数据源补充缺失字段
                    merge_quote_fields(primary_quote, quote)
                    if not primary_quote.needs_supplement():
                        return primary_quote
            except Exception as e:
                circuit_breaker.record_failure(source_key, str(e))
                logger.warning(
                    f"[DataFetcherManager] {stock_code} "
                    f"{fetcher.name} 实时行情失败: {e}"
                )

        return primary_quote

    # ---- 股票名称 ----

    def get_stock_name(
        self,
        stock_code: str,
        allow_realtime: bool = True,
    ) -> Optional[str]:
        """
        获取股票名称（带缓存）。

        查找顺序: 缓存 → 实时行情 → 各 Fetcher API
        """
        code = normalize_stock_code(stock_code)

        with self._stock_name_cache_lock:
            if code in self._stock_name_cache:
                return self._stock_name_cache[code]

        # 尝试从实时行情获取
        if allow_realtime:
            quote = self.get_realtime_quote(code)
            if quote and quote.name:
                with self._stock_name_cache_lock:
                    self._stock_name_cache[code] = quote.name
                return quote.name

        # 逐个 Fetcher 尝试
        for fetcher in self.get_fetchers():
            try:
                name = fetcher.get_stock_name(code)
                if name:
                    with self._stock_name_cache_lock:
                        self._stock_name_cache[code] = name
                    return name
            except Exception:
                continue

        return None

    # ---- 筹码分布 ----

    def get_chip_distribution(
        self,
        stock_code: str,
    ) -> Optional[ChipDistribution]:
        """获取筹码分布（带熔断器）"""
        from data_provider.realtime_types import get_chip_circuit_breaker
        cb = get_chip_circuit_breaker()

        for fetcher in self.get_fetchers():
            source_key = f"chip_{fetcher.name}"
            if not cb.is_available(source_key):
                continue
            try:
                chip = fetcher.get_chip_distribution(stock_code)
                if chip is not None:
                    cb.record_success(source_key)
                    return chip
            except Exception as e:
                cb.record_failure(source_key, str(e))
                logger.warning(
                    f"[DataFetcherManager] {stock_code} "
                    f"{fetcher.name} 筹码分布失败: {e}"
                )

        return None

    # ---- 股票列表 ----

    def get_stock_list(self) -> Optional[pd.DataFrame]:
        """并发获取股票列表并聚合。"""
        fetchers = self.get_fetchers(capability="stock_list")
        diagnostic = {
            "attempted_fetchers": [fetcher.name for fetcher in fetchers],
            "successful_fetchers": [],
            "failed_fetchers": [],
            "failure_reasons": {},
            "best_source": None,
            "merged_sources": [],
        }

        if not fetchers:
            self._last_request_diagnostics["stock_list"] = diagnostic
            return None

        results: Dict[str, pd.DataFrame] = {}
        with ThreadPoolExecutor(
            max_workers=max(1, len(fetchers)),
            thread_name_prefix="stock_list",
        ) as executor:
            futures = {executor.submit(fetcher.get_stock_list): fetcher.name for fetcher in fetchers}
            for future in as_completed(futures, timeout=60):
                name = futures[future]
                try:
                    df = future.result(timeout=20)
                    if df is not None and not df.empty:
                        results[name] = df
                        diagnostic["successful_fetchers"].append(name)
                    else:
                        diagnostic["failed_fetchers"].append(name)
                        diagnostic["failure_reasons"][name] = "返回空数据"
                except Exception as exc:
                    diagnostic["failed_fetchers"].append(name)
                    diagnostic["failure_reasons"][name] = str(exc)
                    logger.warning("[DataFetcherManager] %s 股票列表失败: %s", name, exc)

        if not results:
            self._last_request_diagnostics["stock_list"] = diagnostic
            return None

        normalized_frames = []
        for source_name, df in results.items():
            current = df.copy()
            rename_map = {
                "股票代码": "code",
                "code": "code",
                "symbol": "code",
                "股票名称": "name",
                "股票简称": "name",
                "name": "name",
                "industry": "industry",
                "所属行业": "industry",
            }
            current = current.rename(columns={k: v for k, v in rename_map.items() if k in current.columns})
            if "code" not in current.columns or "name" not in current.columns:
                continue
            current["code"] = current["code"].astype(str).str.strip().str.zfill(6)
            current["name"] = current["name"].astype(str).str.strip()
            current["source"] = source_name
            keep_columns = [col for col in ("code", "name", "industry", "source") if col in current.columns]
            normalized_frames.append(current[keep_columns])

        if not normalized_frames:
            self._last_request_diagnostics["stock_list"] = diagnostic
            return next(iter(results.values()))

        merged = pd.concat(normalized_frames, ignore_index=True)
        merged = merged[merged["code"].astype(bool) & merged["name"].astype(bool)]
        merged = merged.drop_duplicates(subset=["code"], keep="first")
        diagnostic["best_source"] = diagnostic["successful_fetchers"][0]
        diagnostic["merged_sources"] = list(results.keys())
        self._last_request_diagnostics["stock_list"] = diagnostic
        return merged.reset_index(drop=True)

    def get_financial_report_frames(self, stock_code: str) -> Dict[str, Any]:
        """统一财务报表入口，供旧 collector 和 core collector 复用。"""
        capability = "financial_reports"
        startup = self.get_startup_diagnostics()
        attempted = []
        successful = []
        failed = []
        failure_reasons: Dict[str, str] = {}
        unsupported = {
            item["name"]: "capability not supported"
            for item in startup.get("available_fetchers", [])
            if capability not in item.get("capabilities", [])
        }
        frames: Dict[str, pd.DataFrame] = {}

        for api_key, alias in (
            ("financial_income", "income"),
            ("financial_balance", "balance"),
            ("financial_cashflow", "cashflow"),
        ):
            fetcher_name = "AkshareFetcher"
            attempted.append(fetcher_name)
            try:
                frames[alias] = call_akshare(api_key, stock=stock_code)
                successful.append(fetcher_name)
            except Exception as exc:
                failed.append(fetcher_name)
                failure_reasons[f"{fetcher_name}:{alias}"] = str(exc)
                logger.warning("[DataFetcherManager] %s %s 失败: %s", fetcher_name, alias, exc)

        diagnostic = {
            "attempted_fetchers": sorted(set(attempted)),
            "successful_fetchers": sorted(set(successful)),
            "failed_fetchers": sorted(set(failed + list(unsupported.keys()))),
            "failure_reasons": {**unsupported, **failure_reasons},
            "best_source": "AkshareFetcher" if frames else None,
            "merged_sources": ["AkshareFetcher"] if frames else [],
            "consistency_score": 1.0 if frames else 0.0,
        }
        self._last_request_diagnostics[capability] = diagnostic
        frames["diagnostic"] = diagnostic
        return frames

    # ---- 资源释放 ----

    def close(self) -> None:
        """释放所有 Fetcher 资源"""
        for fetcher in self.get_fetchers():
            try:
                fetcher.close()
            except Exception as e:
                logger.warning(f"[DataFetcherManager] {fetcher.name} close 失败: {e}")
