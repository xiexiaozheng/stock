"""
akshare 接口兼容层。

所有 AKShare 接口适配统一读取 data_provider.source_config 中的配置，
避免在业务代码中散落参数白名单、symbol 转换和 fallback 逻辑。
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Iterable, Mapping, Optional

from data_provider.source_config import (
    AKSHARE_API_CONFIGS,
    get_akshare_api_config,
    iter_akshare_sources,
)
from data_provider.error_classifier import ErrorCategory, classify_error
from utils.akshare_runtime import execute_with_proxy_retry

logger = logging.getLogger(__name__)
_PROXY_REFRESH_RETRY_ATTEMPT = 2


class AkshareAPIError(Exception):
    """akshare 接口调用失败异常"""


def _build_legacy_api_map_entry(api_key: str, config: Mapping[str, Any]) -> Dict[str, Any]:
    source_values = list(config.get("sources", {}).values())
    primary_source = source_values[0] if source_values else {}
    return {
        "primary": primary_source.get("api_function"),
        "fallbacks": [source.get("api_function") for source in source_values[1:]],
        "description": config.get("description", api_key),
        "params": primary_source.get("default_params", {}),
    }


AKSHARE_API_MAP = {
    api_key: _build_legacy_api_map_entry(api_key, config)
    for api_key, config in AKSHARE_API_CONFIGS.items()
}


def _resolve_function(module: Any, dotted_path: str):
    """将 'ak.stock_info_a_code_name' 解析为实际函数对象"""
    parts = dotted_path.split(".")
    obj = module
    for part in parts[1:]:
        obj = getattr(obj, part)
    return obj


def _build_call_kwargs(api_config: Mapping[str, Any], business_kwargs: Mapping[str, Any]) -> Dict[str, Any]:
    """按接口白名单构造调用参数。"""
    call_kwargs = {
        **dict(api_config.get("default_params", {})),
        **dict(business_kwargs),
    }

    symbol_param = api_config.get("symbol_param")
    symbol_source_param = api_config.get("symbol_source_param", symbol_param)
    symbol_normalizer = api_config.get("symbol_normalizer")
    if symbol_param:
        raw_symbol = None
        if symbol_source_param and symbol_source_param in call_kwargs:
            raw_symbol = call_kwargs.get(symbol_source_param)
        elif symbol_param in call_kwargs:
            raw_symbol = call_kwargs.get(symbol_param)

        if raw_symbol not in (None, ""):
            call_kwargs[symbol_param] = (
                symbol_normalizer(raw_symbol)
                if callable(symbol_normalizer)
                else raw_symbol
            )
        if symbol_source_param and symbol_source_param != symbol_param:
            call_kwargs.pop(symbol_source_param, None)

    param_transformer = api_config.get("param_transformer")
    if callable(param_transformer):
        call_kwargs = dict(param_transformer(call_kwargs))

    for deprecated_key in api_config.get("deprecated_params", []):
        if deprecated_key != symbol_param:
            call_kwargs.pop(deprecated_key, None)

    supported_params = set(api_config.get("supported_params", []))
    if supported_params:
        call_kwargs = {
            key: value
            for key, value in call_kwargs.items()
            if key in supported_params and value is not None
        }
    else:
        call_kwargs = {
            key: value for key, value in call_kwargs.items() if value is not None
        }

    missing_params = [
        key
        for key in api_config.get("required_params", [])
        if call_kwargs.get(key) in (None, "")
    ]
    if missing_params:
        raise TypeError(f"missing required params: {', '.join(missing_params)}")

    return call_kwargs


def _execute_source_call(source_config: Mapping[str, Any], business_kwargs: Mapping[str, Any]) -> Any:
    source_config = dict(source_config)
    source_config.setdefault(
        "source_name",
        source_config.get("api_function", "unknown").split(".")[-1],
    )
    if not source_config.get("enabled", True):
        raise AttributeError(source_config.get("disabled_reason", "source disabled"))

    call_kwargs = _build_call_kwargs(source_config, business_kwargs)
    retry_policy = source_config.get("retry_policy", {}) or {}
    max_attempts = max(int(retry_policy.get("max_attempts", 1)), 1)
    backoff_seconds = float(retry_policy.get("backoff_seconds", 0.0) or 0.0)
    import akshare as ak

    def _invoke() -> Any:
        func = _resolve_function(ak, source_config["api_function"])
        return func(**call_kwargs)

    return execute_with_proxy_retry(
        "AkShare",
        str(source_config.get("api_function")),
        _invoke,
        max_attempts=max_attempts,
        backoff_seconds=backoff_seconds,
    )


def _find_source_config(api_key: str, source_name: str) -> Dict[str, Any]:
    api_config = get_akshare_api_config(api_key)
    source_config = api_config.get("sources", {}).get(source_name)
    if source_config is None:
        raise KeyError(f"Unknown AKShare source: {api_key}.{source_name}")
    source_config = dict(source_config)
    source_config.setdefault("source_name", source_name)
    return source_config


def get_source_configs(api_key: str, enabled_only: bool = True) -> Iterable[Dict[str, Any]]:
    return list(iter_akshare_sources(api_key, enabled_only=enabled_only))


def call_akshare_source(
    api_key: str,
    source_name: str,
    *,
    raw_exceptions: bool = False,
    **kwargs,
) -> Any:
    """调用指定的 AKShare source spec。"""
    source_config = _find_source_config(api_key, source_name)
    try:
        result = _execute_source_call(source_config, kwargs)
        logger.debug("akshare source %s 调用成功", source_config["api_function"])
        return result
    except Exception as exc:  # noqa: BLE001
        if raw_exceptions:
            raise
        raise AkshareAPIError(
            f"akshare source call failed: {source_config['api_function']}: {exc}"
        ) from exc


def call_akshare(api_key: str, **kwargs) -> Any:
    """统一的 AKShare 调用入口。"""
    config = get_akshare_api_config(api_key)
    all_tried = []

    enabled_sources = list(iter_akshare_sources(api_key, enabled_only=True))
    disabled_sources = list(iter_akshare_sources(api_key, enabled_only=False))
    enabled_names = {source["source_name"] for source in enabled_sources}
    for source in disabled_sources:
        if source["source_name"] not in enabled_names and not source.get("enabled", True):
            all_tried.append(
                {
                    "api": source["api_function"],
                    "error": source.get("disabled_reason", "source disabled"),
                    "category": "disabled",
                }
            )

    for source_config in enabled_sources:
        try:
            result = _execute_source_call(source_config, kwargs)
            logger.debug("akshare 接口 %s 调用成功", source_config["api_function"])
            return result
        except Exception as exc:  # noqa: BLE001
            category = classify_error(exc).value
            all_tried.append(
                {
                    "api": source_config["api_function"],
                    "error": str(exc),
                    "category": category,
                }
            )
            logger.warning(
                "akshare 接口 %s 调用失败 [%s]: %s",
                source_config["api_function"],
                category,
                exc,
            )

    error_lines = [f"akshare 数据采集失败 [{config['description']}]", "尝试过的接口:"]
    for tried in all_tried:
        error_lines.append(
            f"  - {tried['api']}: {tried['error']} [{tried.get('category', 'unknown')}]"
        )
    error_lines += [
        "",
        "配置来源: backend/data_provider/source_config.py",
        "官方文档: https://akshare.akfamily.xyz/data/stock/stock.html#a",
    ]
    raise AkshareAPIError("\n".join(error_lines))
