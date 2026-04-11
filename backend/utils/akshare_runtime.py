"""出站请求运行时代理管理。"""
from __future__ import annotations

import logging
import os
import socket
import threading
import time
from typing import Callable, Optional, TypeVar
from urllib.parse import urlparse

import requests

from config import (
    AKSHARE_PROXY_CHECK_TIMEOUT,
    AKSHARE_PROXY_NO_PROXY,
    AKSHARE_PROXY_TEST_URL,
    AKSHARE_PROXY_URL,
)
from data_provider.error_classifier import ErrorCategory, classify_error

logger = logging.getLogger(__name__)
T = TypeVar("T")

_PROXY_ENV_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)
_NO_PROXY_ENV_KEYS = ("NO_PROXY", "no_proxy")
# 60s 内复用代理探测结果，避免每次 akshare 调用都额外探测一次远程桥接代理。
_PROXY_CACHE_TTL = 60.0
_MIN_PROXY_TIMEOUT_SECONDS = 1.0
_state_lock = threading.Lock()
_state = {
    "checked_at": 0.0,
    "mode": None,
    "proxy_healthy": False,
    "proxy_url": None,
}


def _normalize_mode(mode: Optional[str]) -> str:
    # 历史实现中只要代理健康就默认走代理；因此这里对 None / 非法值都回落为 proxy。
    # 真正的“封禁重试时切到直连/代理”由 toggle_akshare_proxy_mode() 负责。
    return mode if mode in {"proxy", "direct"} else "proxy"


def _resolve_effective_mode(proxy_healthy: bool, mode: Optional[str]) -> str:
    return _normalize_mode(mode) if proxy_healthy else "direct"


def _mode_label(mode_or_proxy_url: Optional[str]) -> str:
    if mode_or_proxy_url == "proxy":
        return "代理"
    if AKSHARE_PROXY_URL and mode_or_proxy_url == AKSHARE_PROXY_URL:
        return "代理"
    return "直连"


def _set_runtime_mode(mode: str) -> None:
    _state["mode"] = mode
    _state["proxy_url"] = AKSHARE_PROXY_URL if _state["proxy_healthy"] and mode == "proxy" else None


def _apply_proxy_env(proxy_url: Optional[str]) -> None:
    for env_name in _PROXY_ENV_KEYS:
        if proxy_url:
            os.environ[env_name] = proxy_url
        else:
            os.environ.pop(env_name, None)

    if AKSHARE_PROXY_NO_PROXY:
        for env_name in _NO_PROXY_ENV_KEYS:
            os.environ[env_name] = AKSHARE_PROXY_NO_PROXY
    else:
        for env_name in _NO_PROXY_ENV_KEYS:
            os.environ.pop(env_name, None)


def _probe_proxy_port(proxy_url: str) -> bool:
    parsed = urlparse(proxy_url)
    if not parsed.hostname or not parsed.port:
        return False
    try:
        with socket.create_connection(
            (parsed.hostname, parsed.port),
            timeout=max(AKSHARE_PROXY_CHECK_TIMEOUT, _MIN_PROXY_TIMEOUT_SECONDS),
        ):
            return True
    except OSError:
        return False


def _probe_proxy_request(proxy_url: str) -> bool:
    if not AKSHARE_PROXY_TEST_URL:
        return True

    try:
        response = requests.get(
            AKSHARE_PROXY_TEST_URL,
            proxies={"http": proxy_url, "https": proxy_url},
            timeout=AKSHARE_PROXY_CHECK_TIMEOUT,
            allow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                ),
            },
        )
        return response.status_code < 500
    except requests.RequestException:
        return False


def _resolve_proxy_mode(force_refresh: bool = False) -> Optional[str]:
    now = time.time()
    with _state_lock:
        checked_at = float(_state["checked_at"] or 0.0)
        if not force_refresh and (now - checked_at) < _PROXY_CACHE_TTL:
            mode = _resolve_effective_mode(_state["proxy_healthy"], _state["mode"])
            return AKSHARE_PROXY_URL if mode == "proxy" else None

    proxy_healthy = False
    mode = "direct"
    if AKSHARE_PROXY_URL:
        if _probe_proxy_port(AKSHARE_PROXY_URL) and _probe_proxy_request(AKSHARE_PROXY_URL):
            proxy_healthy = True
            logger.info("出站代理可用: %s", AKSHARE_PROXY_URL)
        else:
            logger.warning(
                "出站代理不可用，切换为直连: %s",
                AKSHARE_PROXY_URL,
            )

    with _state_lock:
        last_mode = _state["mode"]
        mode = _resolve_effective_mode(proxy_healthy, _state["mode"])
        _state["checked_at"] = now
        _state["proxy_healthy"] = proxy_healthy
        _set_runtime_mode(mode)

    if last_mode and last_mode != mode:
        logger.info("出站网络模式切换为 %s", _mode_label(mode))

    return AKSHARE_PROXY_URL if proxy_healthy and mode == "proxy" else None


def prepare_network_runtime(
    client_name: str = "外部数据源",
    force_refresh: bool = False,
) -> Optional[str]:
    """在每次外部调用前动态切换代理环境变量。"""
    proxy_url = _resolve_proxy_mode(force_refresh=force_refresh)
    _apply_proxy_env(proxy_url)
    logger.debug("%s 当前网络模式: %s", client_name, _mode_label(proxy_url))
    return proxy_url


def toggle_proxy_mode(
    client_name: str = "外部数据源",
    force_refresh: bool = False,
) -> Optional[str]:
    """在代理健康时切换下一次重试使用的网络模式。

    返回代理地址表示下一次重试将走代理；返回 None 表示下一次重试将直连。
    """
    # _resolve_proxy_mode() 会同步刷新/复用 _state 里的代理健康状态，后续直接读取即可。
    _resolve_proxy_mode(force_refresh=force_refresh)

    with _state_lock:
        if not _state["proxy_healthy"]:
            logger.warning("%s 代理不可用，保持直连模式，不执行代理切换", client_name)
            _set_runtime_mode("direct")
            return None

        current_mode = _normalize_mode(_state["mode"])
        next_mode = "direct" if current_mode == "proxy" else "proxy"
        _set_runtime_mode(next_mode)

    logger.info(
        "%s 重试前切换网络模式为 %s",
        client_name,
        _mode_label(next_mode),
    )
    return AKSHARE_PROXY_URL if next_mode == "proxy" else None


def execute_with_proxy_retry(
    client_name: str,
    operation_name: str,
    func: Callable[[], T],
    *,
    max_attempts: int = 1,
    backoff_seconds: float = 0.0,
) -> T:
    """执行外部调用，并在可重试错误时切换直连/代理后重试。"""
    last_error: Optional[Exception] = None

    for attempt in range(1, max(max_attempts, 1) + 1):
        should_force_refresh_proxy = attempt >= 2
        try:
            prepare_network_runtime(client_name=client_name, force_refresh=should_force_refresh_proxy)
            return func()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            category = classify_error(exc)
            should_retry = attempt < max_attempts and category in {
                ErrorCategory.TRANSIENT,
                ErrorCategory.ANTI_CRAWL,
                ErrorCategory.UNKNOWN,
            }
            if not should_retry:
                if category == ErrorCategory.ANTI_CRAWL:
                    logger.warning(
                        "%s %s 疑似被短时封禁，已达到最大重试次数: %s",
                        client_name,
                        operation_name,
                        exc,
                    )
                raise

            sleep_seconds = max(
                backoff_seconds,
                0.5 if category == ErrorCategory.TRANSIENT else 3.0,
            ) * attempt
            next_proxy_url = toggle_proxy_mode(
                client_name=client_name,
                force_refresh=should_force_refresh_proxy,
            )
            logger.warning(
                "%s %s 调用失败 [%s]，已切换为%s并准备重试 (%s/%s)，%.1fs 后重试: %s",
                client_name,
                operation_name,
                category.value,
                _mode_label(next_proxy_url),
                attempt,
                max_attempts,
                sleep_seconds,
                exc,
            )
            time.sleep(sleep_seconds)

    if last_error is not None:
        raise last_error
    raise RuntimeError(f"Unexpected empty execution state for {client_name}.{operation_name}")


def toggle_akshare_proxy_mode(force_refresh: bool = False) -> Optional[str]:
    """兼容旧接口：切换 AkShare 下一次重试使用的网络模式。"""
    return toggle_proxy_mode(client_name="AkShare", force_refresh=force_refresh)


def prepare_akshare_runtime(force_refresh: bool = False) -> Optional[str]:
    """兼容旧接口：在每次 AkShare 调用前动态切换代理。"""
    return prepare_network_runtime(client_name="AkShare", force_refresh=force_refresh)
