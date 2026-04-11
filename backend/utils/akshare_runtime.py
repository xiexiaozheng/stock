"""AkShare 运行时代理管理。"""
from __future__ import annotations

import logging
import os
import socket
import threading
import time
from typing import Optional
from urllib.parse import urlparse

import requests

from config import (
    AKSHARE_PROXY_CHECK_TIMEOUT,
    AKSHARE_PROXY_NO_PROXY,
    AKSHARE_PROXY_TEST_URL,
    AKSHARE_PROXY_URL,
)

logger = logging.getLogger(__name__)

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
_CACHE_TTL_SECONDS = 60.0
_MIN_PROXY_TIMEOUT_SECONDS = 1.0
_state_lock = threading.Lock()
_state = {
    "checked_at": 0.0,
    "mode": None,
    "proxy_url": None,
}


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
        if not force_refresh and (now - checked_at) < _CACHE_TTL_SECONDS:
            return _state["proxy_url"]

    proxy_url: Optional[str] = None
    mode = "direct"
    if AKSHARE_PROXY_URL:
        if _probe_proxy_port(AKSHARE_PROXY_URL) and _probe_proxy_request(AKSHARE_PROXY_URL):
            proxy_url = AKSHARE_PROXY_URL
            mode = "proxy"
            logger.info("AkShare 代理可用，使用 %s", AKSHARE_PROXY_URL)
        else:
            logger.warning(
                "AkShare 代理不可用，切换为直连: %s",
                AKSHARE_PROXY_URL,
            )

    with _state_lock:
        last_mode = _state["mode"]
        _state["checked_at"] = now
        _state["mode"] = mode
        _state["proxy_url"] = proxy_url

    if last_mode and last_mode != mode:
        logger.info("AkShare 网络模式切换为 %s", "代理" if mode == "proxy" else "直连")

    return proxy_url


def prepare_akshare_runtime(force_refresh: bool = False) -> Optional[str]:
    """在每次 AkShare 调用前动态切换代理。"""
    proxy_url = _resolve_proxy_mode(force_refresh=force_refresh)
    _apply_proxy_env(proxy_url)
    return proxy_url
