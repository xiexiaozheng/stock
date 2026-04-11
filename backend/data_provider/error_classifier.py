"""
错误分类器与自适应策略

智能区分:
- API 语法错误 (AttributeError, TypeError) → 停止重试
- 反爬虫错误 (HTTP 403/429, ConnectionError) → 自适应调频
- 临时性错误 (Timeout, 网络波动) → 正常重试

反爬虫对策:
- 动态调整 sleep 间隔
- 自动降低调用频率
- 请求间隔指数退避
"""
import logging
import threading
import time
from enum import Enum
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class ErrorCategory(str, Enum):
    """错误分类"""
    API_SYNTAX = "api_syntax"           # 接口不存在/参数错误 → 不重试
    ANTI_CRAWL = "anti_crawl"           # 反爬虫/限流 → 自适应降频
    TRANSIENT = "transient"             # 临时性网络错误 → 正常重试
    DATA_QUALITY = "data_quality"       # 数据质量问题 → 可切换源
    UNKNOWN = "unknown"                 # 未知错误 → 按临时性处理


# 反爬虫关键词匹配
_ANTI_CRAWL_KEYWORDS = [
    "403", "429", "forbidden", "too many requests",
    "rate limit", "频率", "限流", "封禁", "blocked",
    "access denied", "captcha", "验证码",
    "connection reset", "connection refused",
]

# API 语法错误类型
_API_SYNTAX_EXCEPTIONS = (AttributeError, TypeError, ValueError, ImportError)


def classify_error(error: Exception) -> ErrorCategory:
    """
    分类异常类型。

    :param error: 捕获的异常
    :return: 错误分类枚举
    """
    # 1. API 语法错误 — 停止重试
    if isinstance(error, _API_SYNTAX_EXCEPTIONS):
        return ErrorCategory.API_SYNTAX

    # 2. 检查异常信息中的反爬虫关键词
    error_msg = str(error).lower()

    # HTTP 状态码相关异常
    try:
        # requests.exceptions.HTTPError
        if hasattr(error, "response") and error.response is not None:
            status_code = getattr(error.response, "status_code", 0)
            if status_code in (403, 429, 503):
                return ErrorCategory.ANTI_CRAWL
    except Exception:
        pass

    if any(kw in error_msg for kw in _ANTI_CRAWL_KEYWORDS):
        return ErrorCategory.ANTI_CRAWL

    # 3. 临时性网络错误
    transient_keywords = [
        "timeout", "timed out", "超时",
        "connection", "network", "socket",
        "temporary", "retry", "unavailable",
        "502", "504", "service unavailable",
    ]
    if any(kw in error_msg for kw in transient_keywords):
        return ErrorCategory.TRANSIENT

    # 4. 数据质量问题
    data_keywords = [
        "empty", "no data", "无数据", "空数据",
        "column", "key error", "index error",
    ]
    if any(kw in error_msg for kw in data_keywords):
        return ErrorCategory.DATA_QUALITY

    return ErrorCategory.UNKNOWN


class AdaptiveRateLimiter:
    """
    自适应限流器

    根据错误类型动态调整请求频率:
    - 正常时: 使用 base_interval
    - 遇到反爬虫: 指数退避 (interval *= backoff_factor)
    - 连续成功后: 逐步恢复 (interval *= recovery_factor)

    线程安全。
    """

    def __init__(
        self,
        base_interval: float = 2.0,
        max_interval: float = 60.0,
        backoff_factor: float = 2.0,
        recovery_factor: float = 0.8,
        recovery_threshold: int = 3,
    ):
        """
        :param base_interval: 基础请求间隔 (秒)
        :param max_interval: 最大请求间隔 (秒)
        :param backoff_factor: 遇到反爬虫时的退避倍数
        :param recovery_factor: 连续成功后的恢复因子 (< 1)
        :param recovery_threshold: 连续成功几次后开始恢复
        """
        self.base_interval = base_interval
        self.max_interval = max_interval
        self.backoff_factor = backoff_factor
        self.recovery_factor = recovery_factor
        self.recovery_threshold = recovery_threshold

        self._current_interval: float = base_interval
        self._consecutive_successes: int = 0
        self._consecutive_failures: int = 0
        self._last_request_time: float = 0.0
        self._lock = threading.Lock()

    @property
    def current_interval(self) -> float:
        """当前请求间隔"""
        with self._lock:
            return self._current_interval

    def wait(self) -> float:
        """
        等待直到可以发送下一个请求。

        :return: 实际等待的秒数
        """
        with self._lock:
            now = time.time()
            elapsed = now - self._last_request_time
            wait_time = max(0, self._current_interval - elapsed)

        if wait_time > 0:
            logger.debug(
                f"[AdaptiveRateLimiter] 等待 {wait_time:.2f}s "
                f"(当前间隔: {self._current_interval:.2f}s)"
            )
            time.sleep(wait_time)

        with self._lock:
            self._last_request_time = time.time()

        return wait_time

    def record_success(self) -> None:
        """记录成功请求，逐步恢复频率"""
        with self._lock:
            self._consecutive_successes += 1
            self._consecutive_failures = 0

            if self._consecutive_successes >= self.recovery_threshold:
                new_interval = self._current_interval * self.recovery_factor
                self._current_interval = max(self.base_interval, new_interval)
                self._consecutive_successes = 0
                logger.debug(
                    f"[AdaptiveRateLimiter] 恢复频率: "
                    f"interval={self._current_interval:.2f}s"
                )

    def record_anti_crawl(self) -> None:
        """记录反爬虫错误，指数退避"""
        with self._lock:
            self._consecutive_failures += 1
            self._consecutive_successes = 0

            new_interval = self._current_interval * self.backoff_factor
            self._current_interval = min(self.max_interval, new_interval)
            logger.warning(
                f"[AdaptiveRateLimiter] 反爬虫退避: "
                f"interval={self._current_interval:.2f}s "
                f"(连续失败 {self._consecutive_failures} 次)"
            )

    def record_error(self, error: Exception) -> ErrorCategory:
        """
        记录错误并自动分类处理。

        :return: 错误分类
        """
        category = classify_error(error)

        if category == ErrorCategory.ANTI_CRAWL:
            self.record_anti_crawl()
        elif category == ErrorCategory.API_SYNTAX:
            logger.error(
                f"[AdaptiveRateLimiter] API 语法错误，不重试: {error}"
            )
        # TRANSIENT / DATA_QUALITY / UNKNOWN — 不调整频率

        return category

    def should_retry(self, error: Exception) -> bool:
        """
        判断是否应该重试。

        - API_SYNTAX: 不重试
        - 其他: 重试
        """
        category = classify_error(error)
        return category != ErrorCategory.API_SYNTAX

    def get_status(self) -> Dict[str, Any]:
        """获取限流器状态（调试用）"""
        with self._lock:
            return {
                "current_interval": round(self._current_interval, 2),
                "base_interval": self.base_interval,
                "max_interval": self.max_interval,
                "consecutive_successes": self._consecutive_successes,
                "consecutive_failures": self._consecutive_failures,
            }


# 全局自适应限流器实例 (per source)
_source_limiters: Dict[str, AdaptiveRateLimiter] = {}
_source_limiters_lock = threading.Lock()


def get_adaptive_limiter(
    source_name: str,
    base_interval: float = 2.0,
    max_interval: float = 60.0,
) -> AdaptiveRateLimiter:
    """
    获取指定数据源的自适应限流器（单例模式）。

    :param source_name: 数据源名称
    :param base_interval: 基础请求间隔
    :param max_interval: 最大请求间隔
    """
    with _source_limiters_lock:
        if source_name not in _source_limiters:
            _source_limiters[source_name] = AdaptiveRateLimiter(
                base_interval=base_interval,
                max_interval=max_interval,
            )
        return _source_limiters[source_name]
