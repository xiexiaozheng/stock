"""请求限流器"""
import time
import random
import threading
import logging

logger = logging.getLogger(__name__)


class RateLimiter:
    """令牌桶限流器，支持随机延迟"""

    def __init__(self, min_interval: float = 0.5, max_interval: float = 1.0):
        """
        :param min_interval: 最小请求间隔（秒）
        :param max_interval: 最大请求间隔（秒，用于随机化）
        """
        self.min_interval = min_interval
        self.max_interval = max_interval
        self._last_call_time = 0.0
        self._lock = threading.Lock()

    def wait(self):
        """等待直到可以发送下一个请求"""
        with self._lock:
            now = time.time()
            elapsed = now - self._last_call_time
            interval = random.uniform(self.min_interval, self.max_interval)
            if elapsed < interval:
                sleep_time = interval - elapsed
                logger.debug(f"限流等待 {sleep_time:.2f}s")
                time.sleep(sleep_time)
            self._last_call_time = time.time()

    def __call__(self, func):
        """作为装饰器使用"""
        import functools

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            self.wait()
            return func(*args, **kwargs)

        return wrapper


# 预定义的限流器实例
akshare_limiter = RateLimiter(min_interval=0.5, max_interval=1.0)
chrome_limiter = RateLimiter(min_interval=2.0, max_interval=5.0)
