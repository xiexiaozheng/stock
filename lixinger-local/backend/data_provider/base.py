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
  - 自动按优先级 failover (兼容旧模式)
  - 多数据源字段补充
  - 线程安全

改造说明:
  - 新增 get_daily_data_concurrent(): 并发调用所有可用 Fetcher
  - get_daily_data() 增加 concurrent 参数开关
  - 注册新数据源: YFinance, Longbridge, Eastmoney
  - 使用 error_classifier 智能分类错误
"""
import logging
import random
import threading
import time
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
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

logger = logging.getLogger(__name__)

# 标准化列名 — 所有 Fetcher 输出必须包含这些列
STANDARD_COLUMNS = ["date", "open", "high", "low", "close", "volume", "amount", "pct_chg"]


# =====================================================================
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
      - priority: int      优先级 (0=最高)
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
    priority: int = 99

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

    支持两种模式:
    1. 并发模式 (concurrent=True, 默认): 并发调用所有可用 Fetcher，
       收集结果后交叉校验，返回最佳数据
    2. 顺序 failover 模式 (concurrent=False): 按优先级顺序尝试，
       第一个成功的直接返回

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
        df, source = manager.get_daily_data('600519')  # 默认并发模式
        df, source = manager.get_daily_data('600519', concurrent=False)  # 旧模式
        quote = manager.get_realtime_quote('600519')
        manager.close()
    """

    def __init__(self, fetchers: Optional[List[BaseFetcher]] = None):
        self._fetchers: List[BaseFetcher] = []
        self._fetchers_lock = threading.RLock()
        self._stock_name_cache: Dict[str, str] = {}
        self._stock_name_cache_lock = threading.Lock()

        if fetchers:
            for f in fetchers:
                self.register_fetcher(f)
        else:
            self._auto_register_fetchers()

    def _auto_register_fetchers(self) -> None:
        """
        自动注册所有可用的 Fetcher（按优先级）。

        如果导入失败（缺少依赖），则跳过该 Fetcher。
        注册顺序:
          0. EfinanceFetcher
          1. AkshareFetcher
          2. TushareFetcher
          3. BaostockFetcher
          4. YFinanceFetcher
          5. LongbridgeFetcher
          6. EastmoneyFetcher
        """
        import os
        tushare_token = os.getenv("TUSHARE_TOKEN", "")

        # Priority 0: EfinanceFetcher
        try:
            from data_provider.efinance_fetcher import EfinanceFetcher
            ef = EfinanceFetcher()
            if tushare_token:
                ef.priority = 1
            self.register_fetcher(ef)
            logger.info(f"[DataFetcherManager] 注册 EfinanceFetcher (priority={ef.priority})")
        except ImportError as e:
            logger.warning(f"[DataFetcherManager] EfinanceFetcher 不可用: {e}")

        # Priority 1: AkshareFetcher
        try:
            from data_provider.akshare_fetcher import AkshareFetcher
            af = AkshareFetcher()
            self.register_fetcher(af)
            logger.info(f"[DataFetcherManager] 注册 AkshareFetcher (priority={af.priority})")
        except ImportError as e:
            logger.warning(f"[DataFetcherManager] AkshareFetcher 不可用: {e}")

        # Priority 2: TushareFetcher
        try:
            from data_provider.tushare_fetcher import TushareFetcher
            tf = TushareFetcher(token=tushare_token)
            if tushare_token:
                tf.priority = 0
            self.register_fetcher(tf)
            logger.info(f"[DataFetcherManager] 注册 TushareFetcher (priority={tf.priority})")
        except ImportError as e:
            logger.warning(f"[DataFetcherManager] TushareFetcher 不可用: {e}")

        # Priority 3: BaostockFetcher
        try:
            from data_provider.baostock_fetcher import BaostockFetcher
            bf = BaostockFetcher()
            self.register_fetcher(bf)
            logger.info(f"[DataFetcherManager] 注册 BaostockFetcher (priority={bf.priority})")
        except ImportError as e:
            logger.warning(f"[DataFetcherManager] BaostockFetcher 不可用: {e}")

        # Priority 4: YFinanceFetcher
        try:
            from data_provider.yfinance_fetcher import YFinanceFetcher
            yf = YFinanceFetcher()
            self.register_fetcher(yf)
            logger.info(f"[DataFetcherManager] 注册 YFinanceFetcher (priority={yf.priority})")
        except ImportError as e:
            logger.debug(f"[DataFetcherManager] YFinanceFetcher 不可用: {e}")

        # Priority 5: LongbridgeFetcher
        try:
            from data_provider.longbridge_fetcher import LongbridgeFetcher
            lb = LongbridgeFetcher()
            self.register_fetcher(lb)
            logger.info(f"[DataFetcherManager] 注册 LongbridgeFetcher (priority={lb.priority})")
        except ImportError as e:
            logger.debug(f"[DataFetcherManager] LongbridgeFetcher 不可用: {e}")

        # Priority 6: EastmoneyFetcher
        try:
            from data_provider.eastmoney_fetcher import EastmoneyFetcher
            em = EastmoneyFetcher()
            self.register_fetcher(em)
            logger.info(f"[DataFetcherManager] 注册 EastmoneyFetcher (priority={em.priority})")
        except ImportError as e:
            logger.debug(f"[DataFetcherManager] EastmoneyFetcher 不可用: {e}")

    def register_fetcher(self, fetcher: BaseFetcher) -> None:
        """注册一个 Fetcher 并按优先级排序"""
        with self._fetchers_lock:
            self._fetchers.append(fetcher)
            self._fetchers.sort(key=lambda f: f.priority)

    def get_fetchers(self) -> List[BaseFetcher]:
        """返回按优先级排序的 Fetcher 列表"""
        with self._fetchers_lock:
            return list(self._fetchers)

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

        :param concurrent: True=并发多源+交叉校验, False=按优先级 failover
        :return: (DataFrame, source_name)
        :raises DataFetchError: 所有数据源都失败时
        """
        if concurrent:
            return self.get_daily_data_concurrent(
                stock_code, start_date, end_date, days
            )
        return self._get_daily_data_failover(
            stock_code, start_date, end_date, days
        )

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
        fetchers = self.get_fetchers()
        errors: List[str] = []
        source_results: Dict[str, pd.DataFrame] = {}

        def _fetch_from_source(fetcher: BaseFetcher) -> Tuple[str, pd.DataFrame]:
            """从单个数据源获取数据"""
            source_key = f"daily_{fetcher.name}"
            if not circuit_breaker.is_available(source_key):
                return fetcher.name, pd.DataFrame()
            try:
                df = fetcher.get_daily_data(
                    stock_code,
                    start_date=start_date,
                    end_date=end_date,
                    days=days,
                )
                if df is not None and not df.empty:
                    circuit_breaker.record_success(source_key)
                    return fetcher.name, df
                circuit_breaker.record_inconclusive(source_key)
                return fetcher.name, pd.DataFrame()
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
                return fetcher.name, pd.DataFrame()

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
                        name, df = future.result(timeout=CONCURRENT_FETCH_TIMEOUT / 2)
                        if df is not None and not df.empty:
                            source_results[name] = df
                        elif name:
                            errors.append(f"{name}: 返回空数据")
                    except Exception as e:
                        fetcher_name = futures[future]
                        errors.append(f"{fetcher_name}: {e}")
        except Exception as e:
            logger.warning(
                f"[DataFetcherManager] 并发执行异常，降级为 failover: {e}"
            )
            return self._get_daily_data_failover(
                stock_code, start_date, end_date, days
            )

        if not source_results:
            raise DataFetchError(
                f"所有数据源获取 {stock_code} 日K线均失败 (并发模式):\n"
                + "\n".join(f"  - {e}" for e in errors)
            )

        # 单源直接返回
        if len(source_results) == 1:
            source_name = next(iter(source_results))
            df = source_results[source_name]
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
        """
        原有的按优先级顺序 failover 模式。

        :return: (DataFrame, fetcher_name)
        :raises DataFetchError: 所有数据源都失败时
        """
        circuit_breaker = get_daily_circuit_breaker()
        errors: List[str] = []

        for fetcher in self.get_fetchers():
            source_key = f"daily_{fetcher.name}"

            if not circuit_breaker.is_available(source_key):
                errors.append(f"{fetcher.name}: 熔断中")
                continue

            try:
                df = fetcher.get_daily_data(
                    stock_code,
                    start_date=start_date,
                    end_date=end_date,
                    days=days,
                )
                if df is not None and not df.empty:
                    circuit_breaker.record_success(source_key)
                    logger.info(
                        f"[DataFetcherManager] {stock_code} 日K线 "
                        f"来自 {fetcher.name}, {len(df)} 行"
                    )
                    return df, fetcher.name
                else:
                    errors.append(f"{fetcher.name}: 返回空数据")
                    circuit_breaker.record_inconclusive(source_key)
            except Exception as e:
                circuit_breaker.record_failure(source_key, str(e))
                errors.append(f"{fetcher.name}: {e}")
                logger.warning(
                    f"[DataFetcherManager] {stock_code} "
                    f"{fetcher.name} 日K线失败: {e}"
                )

        raise DataFetchError(
            f"所有数据源获取 {stock_code} 日K线均失败:\n"
            + "\n".join(f"  - {e}" for e in errors)
        )

    # ---- 实时行情（多源补充）----

    def get_realtime_quote(
        self,
        stock_code: str,
    ) -> Optional[UnifiedRealtimeQuote]:
        """
        获取实时行情，尝试所有 Fetcher 并合并缺失字段。

        策略:
        1. 从最高优先级开始，取到有效报价
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
        """获取A股股票列表（从第一个成功的 Fetcher 返回）"""
        for fetcher in self.get_fetchers():
            try:
                df = fetcher.get_stock_list()
                if df is not None and not df.empty:
                    return df
            except Exception as e:
                logger.warning(
                    f"[DataFetcherManager] {fetcher.name} 股票列表失败: {e}"
                )
        return None

    # ---- 资源释放 ----

    def close(self) -> None:
        """释放所有 Fetcher 资源"""
        for fetcher in self.get_fetchers():
            try:
                fetcher.close()
            except Exception as e:
                logger.warning(f"[DataFetcherManager] {fetcher.name} close 失败: {e}")
