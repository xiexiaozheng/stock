from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable, Dict, Iterable, Mapping, Optional

AKSHARE_STOCK_DOC_REFERENCE = "https://akshare.akfamily.xyz/data/stock/stock.html#a"
AKSHARE_DOC_LAST_VERIFIED = "2026-04-10"


def _strip_exchange_affixes(code: str) -> str:
    raw = str(code or "").strip()
    if "." in raw:
        raw = raw.split(".")[0]
    upper = raw.upper()
    for prefix in ("SH", "SZ", "BJ"):
        if upper.startswith(prefix):
            raw = raw[2:]
            break
    return raw.zfill(6)


def normalize_pure_code(code: str) -> str:
    return _strip_exchange_affixes(code)


def normalize_prefixed_lower(code: str) -> str:
    pure = _strip_exchange_affixes(code)
    prefix = "sh" if pure.startswith(("6", "9")) else "sz"
    return f"{prefix}{pure}"


def normalize_prefixed_upper(code: str) -> str:
    pure = _strip_exchange_affixes(code)
    prefix = "SH" if pure.startswith(("6", "9")) else "SZ"
    return f"{prefix}{pure}"


def normalize_date_text(value: Any, output_format: str = "%Y%m%d") -> Any:
    if value is None:
        return None
    if hasattr(value, "strftime"):
        return value.strftime(output_format)
    text = str(value).strip()
    if not text:
        return text
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d"):
        try:
            from datetime import datetime

            return datetime.strptime(text, fmt).strftime(output_format)
        except ValueError:
            continue
    return text


def normalize_date_kwargs(kwargs: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(kwargs)
    for key in ("start_date", "end_date"):
        if key in normalized and normalized[key] is not None:
            normalized[key] = normalize_date_text(normalized[key], "%Y%m%d")
    return normalized


def identity_kwargs(kwargs: Dict[str, Any]) -> Dict[str, Any]:
    return dict(kwargs)


def clone_config(config: Mapping[str, Any]) -> Dict[str, Any]:
    return deepcopy(dict(config))


FRAMEWORK_CONFIGS: Dict[str, Dict[str, Any]] = {
    "akshare": {
        "name": "AkshareFetcher",
        "fetcher_class": "data_provider.akshare_fetcher.AkshareFetcher",
        "enabled_by_default": True,
        "required_dependency": "akshare",
        "required_env": [],
        "optional_env": [],
        "constructor_env": {},
        "capabilities": [
            "daily_quotes",
            "stock_list",
            "stock_realtime",
            "financial_reports",
            "industries",
            "dividends",
            "valuation_indicator",
        ],
        "startup_check": "dependency_import",
        "unavailable_reason_template": "{name} unavailable: {reason}",
    },
    "tushare": {
        "name": "TushareFetcher",
        "fetcher_class": "data_provider.tushare_fetcher.TushareFetcher",
        "enabled_by_default": True,
        "required_dependency": "tushare",
        "required_env": [],
        "optional_env": ["TUSHARE_TOKEN"],
        "constructor_env": {"token": "TUSHARE_TOKEN"},
        "capabilities": ["daily_quotes", "stock_list", "stock_realtime", "chip_distribution"],
        "startup_check": "dependency_import",
        "unavailable_reason_template": "{name} unavailable: {reason}",
    },
    "efinance": {
        "name": "EfinanceFetcher",
        "fetcher_class": "data_provider.efinance_fetcher.EfinanceFetcher",
        "enabled_by_default": True,
        "required_dependency": "efinance",
        "required_env": [],
        "optional_env": [],
        "constructor_env": {},
        "capabilities": ["daily_quotes", "stock_list", "stock_realtime"],
        "startup_check": "dependency_import",
        "unavailable_reason_template": "{name} unavailable: {reason}",
    },
    "baostock": {
        "name": "BaostockFetcher",
        "fetcher_class": "data_provider.baostock_fetcher.BaostockFetcher",
        "enabled_by_default": True,
        "required_dependency": "baostock",
        "required_env": [],
        "optional_env": [],
        "constructor_env": {},
        "capabilities": ["daily_quotes", "stock_list", "adjust_factor"],
        "startup_check": "dependency_import",
        "unavailable_reason_template": "{name} unavailable: {reason}",
    },
    "yfinance": {
        "name": "YFinanceFetcher",
        "fetcher_class": "data_provider.yfinance_fetcher.YFinanceFetcher",
        "enabled_by_default": True,
        "required_dependency": "yfinance",
        "required_env": [],
        "optional_env": [],
        "constructor_env": {},
        "capabilities": ["daily_quotes"],
        "startup_check": "dependency_import",
        "unavailable_reason_template": "{name} unavailable: {reason}",
    },
    "longbridge": {
        "name": "LongbridgeFetcher",
        "fetcher_class": "data_provider.longbridge_fetcher.LongbridgeFetcher",
        "enabled_by_default": True,
        "required_dependency": "longport",
        "required_env": [
            "LONGBRIDGE_APP_KEY",
            "LONGBRIDGE_APP_SECRET",
            "LONGBRIDGE_ACCESS_TOKEN",
        ],
        "optional_env": [],
        "constructor_env": {},
        "capabilities": ["daily_quotes", "stock_realtime"],
        "startup_check": "dependency_and_env",
        "unavailable_reason_template": "{name} unavailable: {reason}",
    },
    "eastmoney": {
        "name": "EastmoneyFetcher",
        "fetcher_class": "data_provider.eastmoney_fetcher.EastmoneyFetcher",
        "enabled_by_default": True,
        "required_dependency": "requests",
        "required_env": [],
        "optional_env": [],
        "constructor_env": {},
        "capabilities": ["daily_quotes", "stock_realtime"],
        "startup_check": "dependency_import",
        "unavailable_reason_template": "{name} unavailable: {reason}",
    },
}


CROSS_VALIDATION_CONFIGS: Dict[str, Dict[str, Any]] = {
    "daily_quotes": {
        "standard_fields": ["date", "open", "high", "low", "close", "volume", "amount", "pct_chg"],
        "validation_fields": ["open", "high", "low", "close", "volume"],
        "allowed_missing_fields": ["amount", "pct_chg"],
        "tolerances": {
            "open": 0.005,
            "high": 0.005,
            "low": 0.005,
            "close": 0.005,
            "volume": 0.05,
            "amount": 0.05,
            "pct_chg": 0.01,
        },
    }
}


AKSHARE_API_CONFIGS: Dict[str, Dict[str, Any]] = {
    "stock_list": {
        "description": "获取 A 股股票列表",
        "capability": "stock_list",
        "framework": "akshare",
        "sources": {
            "stock_info_a_code_name": {
                "source_name": "stock_info_a_code_name",
                "api_function": "ak.stock_info_a_code_name",
                "enabled": True,
                "doc_reference": AKSHARE_STOCK_DOC_REFERENCE,
                "last_verified": AKSHARE_DOC_LAST_VERIFIED,
                "signature": "stock_info_a_code_name()",
                "supported_params": [],
                "required_params": [],
                "default_params": {},
                "deprecated_params": [],
                "param_transformer": identity_kwargs,
                "field_mapping": {
                    "code": "code",
                    "股票代码": "code",
                    "name": "name",
                    "股票简称": "name",
                    "industry": "industry",
                },
                "supports_cross_validation": False,
                "timeout": 20.0,
                "retry_policy": {"max_attempts": 1, "backoff_seconds": 0.0},
            }
        },
    },
    "daily_quotes": {
        "description": "获取 A 股日线行情",
        "capability": "daily_quotes",
        "framework": "akshare",
        "sources": {
            "stock_zh_a_hist": {
                "source_name": "stock_zh_a_hist",
                "api_function": "ak.stock_zh_a_hist",
                "enabled": True,
                "doc_reference": AKSHARE_STOCK_DOC_REFERENCE,
                "last_verified": AKSHARE_DOC_LAST_VERIFIED,
                "signature": "stock_zh_a_hist(symbol, period, start_date, end_date, adjust, timeout=None)",
                "supported_params": ["symbol", "period", "start_date", "end_date", "adjust", "timeout"],
                "required_params": ["symbol"],
                "default_params": {"period": "daily", "adjust": "qfq", "timeout": 20.0},
                "deprecated_params": ["symbol_type"],
                "symbol_param": "symbol",
                "symbol_source_param": "symbol",
                "symbol_normalizer": normalize_pure_code,
                "param_transformer": normalize_date_kwargs,
                "field_mapping": {
                    "日期": "date",
                    "开盘": "open",
                    "最高": "high",
                    "最低": "low",
                    "收盘": "close",
                    "成交量": "volume",
                    "成交额": "amount",
                    "涨跌幅": "pct_chg",
                },
                "supports_cross_validation": True,
                "timeout": 20.0,
                "retry_policy": {"max_attempts": 3, "backoff_seconds": 1.5},
            },
            "stock_zh_a_daily": {
                "source_name": "stock_zh_a_daily",
                "api_function": "ak.stock_zh_a_daily",
                "enabled": True,
                "doc_reference": AKSHARE_STOCK_DOC_REFERENCE,
                "last_verified": AKSHARE_DOC_LAST_VERIFIED,
                "signature": "stock_zh_a_daily(symbol, start_date, end_date, adjust='')",
                "supported_params": ["symbol", "start_date", "end_date", "adjust"],
                "required_params": ["symbol"],
                "default_params": {"adjust": "qfq"},
                "deprecated_params": ["period", "symbol_type", "timeout"],
                "symbol_param": "symbol",
                "symbol_source_param": "symbol",
                "symbol_normalizer": normalize_prefixed_lower,
                "param_transformer": normalize_date_kwargs,
                "field_mapping": {
                    "date": "date",
                    "open": "open",
                    "high": "high",
                    "low": "low",
                    "close": "close",
                    "volume": "volume",
                },
                "supports_cross_validation": True,
                "timeout": 20.0,
                "retry_policy": {"max_attempts": 1, "backoff_seconds": 0.0},
            },
            "stock_zh_a_hist_tx": {
                "source_name": "stock_zh_a_hist_tx",
                "api_function": "ak.stock_zh_a_hist_tx",
                "enabled": True,
                "doc_reference": AKSHARE_STOCK_DOC_REFERENCE,
                "last_verified": AKSHARE_DOC_LAST_VERIFIED,
                "signature": "stock_zh_a_hist_tx(symbol, start_date, end_date, adjust='', timeout=None)",
                "supported_params": ["symbol", "start_date", "end_date", "adjust", "timeout"],
                "required_params": ["symbol"],
                "default_params": {"adjust": "qfq", "timeout": 20.0},
                "deprecated_params": ["period", "symbol_type"],
                "symbol_param": "symbol",
                "symbol_source_param": "symbol",
                "symbol_normalizer": normalize_prefixed_lower,
                "param_transformer": normalize_date_kwargs,
                "field_mapping": {
                    "date": "date",
                    "open": "open",
                    "high": "high",
                    "low": "low",
                    "close": "close",
                    "amount": "amount",
                    "volume": "volume",
                },
                "supports_cross_validation": True,
                "timeout": 20.0,
                "retry_policy": {"max_attempts": 1, "backoff_seconds": 0.0},
            },
        },
    },
    "financial_income": {
        "description": "获取利润表",
        "capability": "financial_reports",
        "framework": "akshare",
        "sources": {
            "stock_financial_report_sina": {
                "source_name": "stock_financial_report_sina",
                "api_function": "ak.stock_financial_report_sina",
                "enabled": True,
                "doc_reference": AKSHARE_STOCK_DOC_REFERENCE,
                "last_verified": AKSHARE_DOC_LAST_VERIFIED,
                "signature": "stock_financial_report_sina(stock, symbol)",
                "supported_params": ["stock", "symbol"],
                "required_params": ["stock", "symbol"],
                "default_params": {"symbol": "利润表"},
                "deprecated_params": ["symbol_type", "period"],
                "symbol_param": "stock",
                "symbol_source_param": "stock",
                "symbol_normalizer": normalize_prefixed_lower,
                "param_transformer": identity_kwargs,
                "field_mapping": {"报告期": "report_date", "净利润": "net_profit", "营业总收入": "total_revenue"},
                "supports_cross_validation": False,
                "timeout": 20.0,
                "retry_policy": {"max_attempts": 1, "backoff_seconds": 0.0},
            },
            "stock_profit_sheet_by_yearly_em": {
                "source_name": "stock_profit_sheet_by_yearly_em",
                "api_function": "ak.stock_profit_sheet_by_yearly_em",
                "enabled": True,
                "doc_reference": AKSHARE_STOCK_DOC_REFERENCE,
                "last_verified": AKSHARE_DOC_LAST_VERIFIED,
                "signature": "stock_profit_sheet_by_yearly_em(symbol)",
                "supported_params": ["symbol"],
                "required_params": ["symbol"],
                "default_params": {},
                "deprecated_params": ["stock", "symbol_type", "period"],
                "symbol_param": "symbol",
                "symbol_source_param": "stock",
                "symbol_normalizer": normalize_prefixed_upper,
                "param_transformer": identity_kwargs,
                "field_mapping": {"REPORT_DATE": "report_date", "净利润": "net_profit", "营业总收入": "total_revenue"},
                "supports_cross_validation": False,
                "timeout": 20.0,
                "retry_policy": {"max_attempts": 1, "backoff_seconds": 0.0},
            },
        },
    },
    "financial_balance": {
        "description": "获取资产负债表",
        "capability": "financial_reports",
        "framework": "akshare",
        "sources": {
            "stock_financial_report_sina": {
                "source_name": "stock_financial_report_sina",
                "api_function": "ak.stock_financial_report_sina",
                "enabled": True,
                "doc_reference": AKSHARE_STOCK_DOC_REFERENCE,
                "last_verified": AKSHARE_DOC_LAST_VERIFIED,
                "signature": "stock_financial_report_sina(stock, symbol)",
                "supported_params": ["stock", "symbol"],
                "required_params": ["stock", "symbol"],
                "default_params": {"symbol": "资产负债表"},
                "deprecated_params": ["symbol_type", "period"],
                "symbol_param": "stock",
                "symbol_source_param": "stock",
                "symbol_normalizer": normalize_prefixed_lower,
                "param_transformer": identity_kwargs,
                "field_mapping": {"报告期": "report_date", "资产总计": "total_assets", "负债合计": "total_liabilities"},
                "supports_cross_validation": False,
                "timeout": 20.0,
                "retry_policy": {"max_attempts": 1, "backoff_seconds": 0.0},
            },
            "stock_balance_sheet_by_yearly_em": {
                "source_name": "stock_balance_sheet_by_yearly_em",
                "api_function": "ak.stock_balance_sheet_by_yearly_em",
                "enabled": True,
                "doc_reference": AKSHARE_STOCK_DOC_REFERENCE,
                "last_verified": AKSHARE_DOC_LAST_VERIFIED,
                "signature": "stock_balance_sheet_by_yearly_em(symbol)",
                "supported_params": ["symbol"],
                "required_params": ["symbol"],
                "default_params": {},
                "deprecated_params": ["stock", "symbol_type", "period"],
                "symbol_param": "symbol",
                "symbol_source_param": "stock",
                "symbol_normalizer": normalize_prefixed_upper,
                "param_transformer": identity_kwargs,
                "field_mapping": {"REPORT_DATE": "report_date", "资产总计": "total_assets", "负债合计": "total_liabilities"},
                "supports_cross_validation": False,
                "timeout": 20.0,
                "retry_policy": {"max_attempts": 1, "backoff_seconds": 0.0},
            },
        },
    },
    "financial_cashflow": {
        "description": "获取现金流量表",
        "capability": "financial_reports",
        "framework": "akshare",
        "sources": {
            "stock_financial_report_sina": {
                "source_name": "stock_financial_report_sina",
                "api_function": "ak.stock_financial_report_sina",
                "enabled": True,
                "doc_reference": AKSHARE_STOCK_DOC_REFERENCE,
                "last_verified": AKSHARE_DOC_LAST_VERIFIED,
                "signature": "stock_financial_report_sina(stock, symbol)",
                "supported_params": ["stock", "symbol"],
                "required_params": ["stock", "symbol"],
                "default_params": {"symbol": "现金流量表"},
                "deprecated_params": ["symbol_type", "period"],
                "symbol_param": "stock",
                "symbol_source_param": "stock",
                "symbol_normalizer": normalize_prefixed_lower,
                "param_transformer": identity_kwargs,
                "field_mapping": {"报告期": "report_date", "经营活动产生的现金流量净额": "operating_cash_flow"},
                "supports_cross_validation": False,
                "timeout": 20.0,
                "retry_policy": {"max_attempts": 1, "backoff_seconds": 0.0},
            },
            "stock_cash_flow_sheet_by_yearly_em": {
                "source_name": "stock_cash_flow_sheet_by_yearly_em",
                "api_function": "ak.stock_cash_flow_sheet_by_yearly_em",
                "enabled": True,
                "doc_reference": AKSHARE_STOCK_DOC_REFERENCE,
                "last_verified": AKSHARE_DOC_LAST_VERIFIED,
                "signature": "stock_cash_flow_sheet_by_yearly_em(symbol)",
                "supported_params": ["symbol"],
                "required_params": ["symbol"],
                "default_params": {},
                "deprecated_params": ["stock", "symbol_type", "period"],
                "symbol_param": "symbol",
                "symbol_source_param": "stock",
                "symbol_normalizer": normalize_prefixed_upper,
                "param_transformer": identity_kwargs,
                "field_mapping": {"REPORT_DATE": "report_date", "经营活动产生的现金流量净额": "operating_cash_flow"},
                "supports_cross_validation": False,
                "timeout": 20.0,
                "retry_policy": {"max_attempts": 1, "backoff_seconds": 0.0},
            },
        },
    },
    "valuation_indicator": {
        "description": "获取估值指标历史序列",
        "capability": "valuation_indicator",
        "framework": "akshare",
        "sources": {
            "stock_a_indicator_lg": {
                "source_name": "stock_a_indicator_lg",
                "api_function": "ak.stock_a_indicator_lg",
                "enabled": False,
                "disabled_reason": "AKShare 当前版本与官方文档中均未提供 stock_a_indicator_lg，暂未找到等价历史估值替代接口",
                "doc_reference": AKSHARE_STOCK_DOC_REFERENCE,
                "last_verified": AKSHARE_DOC_LAST_VERIFIED,
                "signature": "unavailable",
                "supported_params": ["symbol"],
                "required_params": ["symbol"],
                "default_params": {},
                "deprecated_params": ["symbol_type", "period"],
                "symbol_param": "symbol",
                "symbol_source_param": "symbol",
                "symbol_normalizer": normalize_pure_code,
                "param_transformer": identity_kwargs,
                "field_mapping": {},
                "supports_cross_validation": False,
                "timeout": 20.0,
                "retry_policy": {"max_attempts": 1, "backoff_seconds": 0.0},
            }
        },
    },
    "dividends": {
        "description": "获取分红数据",
        "capability": "dividends",
        "framework": "akshare",
        "sources": {
            "stock_fhps_detail_ths": {
                "source_name": "stock_fhps_detail_ths",
                "api_function": "ak.stock_fhps_detail_ths",
                "enabled": True,
                "doc_reference": AKSHARE_STOCK_DOC_REFERENCE,
                "last_verified": AKSHARE_DOC_LAST_VERIFIED,
                "signature": "stock_fhps_detail_ths(symbol)",
                "supported_params": ["symbol"],
                "required_params": ["symbol"],
                "default_params": {},
                "deprecated_params": ["stock", "symbol_type", "period"],
                "symbol_param": "symbol",
                "symbol_source_param": "symbol",
                "symbol_normalizer": normalize_pure_code,
                "param_transformer": identity_kwargs,
                "field_mapping": {},
                "supports_cross_validation": False,
                "timeout": 20.0,
                "retry_policy": {"max_attempts": 1, "backoff_seconds": 0.0},
            }
        },
    },
    "industry_list": {
        "description": "获取行业板块列表",
        "capability": "industries",
        "framework": "akshare",
        "sources": {
            "stock_board_industry_name_em": {
                "source_name": "stock_board_industry_name_em",
                "api_function": "ak.stock_board_industry_name_em",
                "enabled": True,
                "doc_reference": AKSHARE_STOCK_DOC_REFERENCE,
                "last_verified": AKSHARE_DOC_LAST_VERIFIED,
                "signature": "stock_board_industry_name_em()",
                "supported_params": [],
                "required_params": [],
                "default_params": {},
                "deprecated_params": ["stock", "symbol_type", "period"],
                "param_transformer": identity_kwargs,
                "field_mapping": {},
                "supports_cross_validation": False,
                "timeout": 20.0,
                "retry_policy": {"max_attempts": 1, "backoff_seconds": 0.0},
            }
        },
    },
    "industry_constituents": {
        "description": "获取行业板块成分股",
        "capability": "industries",
        "framework": "akshare",
        "sources": {
            "stock_board_industry_cons_em": {
                "source_name": "stock_board_industry_cons_em",
                "api_function": "ak.stock_board_industry_cons_em",
                "enabled": True,
                "doc_reference": AKSHARE_STOCK_DOC_REFERENCE,
                "last_verified": AKSHARE_DOC_LAST_VERIFIED,
                "signature": "stock_board_industry_cons_em(symbol)",
                "supported_params": ["symbol"],
                "required_params": ["symbol"],
                "default_params": {},
                "deprecated_params": ["stock", "symbol_type", "period"],
                "symbol_param": "symbol",
                "symbol_source_param": "symbol",
                "symbol_normalizer": lambda value: str(value).strip(),
                "param_transformer": identity_kwargs,
                "field_mapping": {},
                "supports_cross_validation": False,
                "timeout": 20.0,
                "retry_policy": {"max_attempts": 1, "backoff_seconds": 0.0},
            }
        },
    },
    "stock_realtime": {
        "description": "获取 A 股实时行情",
        "capability": "stock_realtime",
        "framework": "akshare",
        "sources": {
            "stock_zh_a_spot_em": {
                "source_name": "stock_zh_a_spot_em",
                "api_function": "ak.stock_zh_a_spot_em",
                "enabled": True,
                "doc_reference": AKSHARE_STOCK_DOC_REFERENCE,
                "last_verified": AKSHARE_DOC_LAST_VERIFIED,
                "signature": "stock_zh_a_spot_em()",
                "supported_params": [],
                "required_params": [],
                "default_params": {},
                "deprecated_params": [],
                "param_transformer": identity_kwargs,
                "field_mapping": {},
                "supports_cross_validation": False,
                "timeout": 20.0,
                "retry_policy": {"max_attempts": 2, "backoff_seconds": 1.0},
            }
        },
    },
}


def get_framework_configs() -> Dict[str, Dict[str, Any]]:
    return clone_config(FRAMEWORK_CONFIGS)


def get_framework_config(framework_key: str) -> Dict[str, Any]:
    config = FRAMEWORK_CONFIGS.get(framework_key)
    if config is None:
        raise KeyError(f"Unknown framework config: {framework_key}")
    return clone_config(config)


def get_cross_validation_config(capability: str) -> Dict[str, Any]:
    return clone_config(CROSS_VALIDATION_CONFIGS.get(capability, {}))


def get_akshare_api_config(api_key: str) -> Dict[str, Any]:
    config = AKSHARE_API_CONFIGS.get(api_key)
    if config is None:
        raise KeyError(f"Unknown AKShare API key: {api_key}")
    return clone_config(config)


def iter_akshare_sources(api_key: str, enabled_only: bool = True) -> Iterable[Dict[str, Any]]:
    api_config = AKSHARE_API_CONFIGS.get(api_key, {})
    for source_name, source_config in api_config.get("sources", {}).items():
        config = clone_config(source_config)
        config.setdefault("source_name", source_name)
        if enabled_only and not config.get("enabled", True):
            continue
        yield config


def build_unavailable_reason(config: Mapping[str, Any], reason: str) -> str:
    template = config.get("unavailable_reason_template", "{name} unavailable: {reason}")
    return template.format(name=config.get("name", "unknown"), reason=reason)
