"""重试装饰器"""
import time
import functools
import logging
from typing import Callable, Type, Tuple

logger = logging.getLogger(__name__)


def retry(
    max_retries: int = 3,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    base_delay: float = 1.0,
    backoff: float = 2.0,
    on_failure: Callable = None,
):
    """
    指数退避重试装饰器。

    :param max_retries: 最大重试次数
    :param exceptions: 捕获的异常类型元组
    :param base_delay: 初始等待时间（秒）
    :param backoff: 退避倍数
    :param on_failure: 每次失败时的回调函数 on_failure(attempt, exception)
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if on_failure:
                        on_failure(attempt, e)
                    if attempt < max_retries:
                        delay = base_delay * (backoff ** attempt)
                        logger.warning(
                            f"函数 {func.__name__} 第 {attempt + 1}/{max_retries} 次重试失败: {e}，"
                            f"{delay:.1f}s 后重试..."
                        )
                        time.sleep(delay)
                    else:
                        logger.error(
                            f"函数 {func.__name__} 已重试 {max_retries} 次，最终失败: {e}"
                        )
            raise last_exception
        return wrapper
    return decorator
