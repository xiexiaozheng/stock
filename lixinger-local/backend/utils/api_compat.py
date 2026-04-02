"""
akshare 接口兼容层

由于 akshare 接口更新频繁，所有 akshare 调用都通过此模块统一入口。
当接口变更时，只需修改此文件的映射表即可，无需改动业务代码。
"""
import logging
from typing import Any

logger = logging.getLogger(__name__)


class AkshareAPIError(Exception):
    """akshare 接口调用失败异常"""
    pass


# 接口映射配置：主接口 + 备选接口列表
AKSHARE_API_MAP = {
    "stock_list": {
        "primary": "ak.stock_info_a_code_name",
        "fallbacks": [],
        "description": "获取A股股票列表",
        "params": {},
    },
    "daily_quotes": {
        "primary": "ak.stock_zh_a_hist",
        "fallbacks": [],
        "description": "获取日K线行情数据",
        "params": {"adjust": "qfq"},  # 前复权
    },
    "financial_income": {
        "primary": "ak.stock_financial_report_sina",
        "fallbacks": [
            "ak.stock_financial_abstract_sina",
        ],
        "description": "获取利润表",
        "params": {"symbol": None, "symbol_type": "income"},  # [需验证] symbol_type 参数名可能为 report
    },
    "financial_balance": {
        "primary": "ak.stock_financial_report_sina",
        "fallbacks": [
            "ak.stock_financial_abstract_sina",
        ],
        "description": "获取资产负债表",
        "params": {"symbol": None, "symbol_type": "balance"},  # [需验证]
    },
    "financial_cashflow": {
        "primary": "ak.stock_financial_report_sina",
        "fallbacks": [
            "ak.stock_financial_abstract_sina",
        ],
        "description": "获取现金流量表",
        "params": {"symbol": None, "symbol_type": "cash_flow"},  # [需验证]
    },
    "valuation_indicator": {
        "primary": "ak.stock_a_indicator_lg",
        "fallbacks": [],
        "description": "获取PE/PB/PS等估值指标历史序列",
        "params": {},
    },
    "dividends": {
        "primary": "ak.stock_dividents_cninfo",
        "fallbacks": [],
        "description": "获取分红数据",
        "params": {},
    },
    "industry_list": {
        "primary": "ak.stock_board_industry_name_em",
        "fallbacks": [],
        "description": "获取行业板块列表",
        "params": {},
    },
    "industry_constituents": {
        "primary": "ak.stock_board_industry_cons_em",
        "fallbacks": [],
        "description": "获取板块成分股",
        "params": {},
    },
    "stock_realtime": {
        "primary": "ak.stock_zh_a_spot_em",
        "fallbacks": [],
        "description": "获取A股实时行情（全市场）",
        "params": {},
    },
}


def _resolve_function(module: Any, dotted_path: str):
    """将 'ak.stock_info_a_code_name' 解析为实际函数对象"""
    parts = dotted_path.split(".")
    obj = module
    for part in parts[1:]:  # 跳过 'ak'
        obj = getattr(obj, part)
    return obj


def call_akshare(api_key: str, **kwargs) -> Any:
    """
    统一的 akshare 调用入口。

    流程：
    1. 从 AKSHARE_API_MAP 获取主接口和备选接口
    2. 先尝试主接口
    3. 主接口失败时，依次尝试 fallbacks
    4. 所有接口都失败时，抛出带有详细信息的 AkshareAPIError
    """
    import akshare as ak

    config = AKSHARE_API_MAP.get(api_key)
    if not config:
        raise ValueError(f"未知的 API key: {api_key}，请检查 AKSHARE_API_MAP 配置")

    # 合并默认参数和传入参数（传入参数优先）
    default_params = {k: v for k, v in config.get("params", {}).items() if v is not None}
    merged_kwargs = {**default_params, **kwargs}

    all_tried = []
    api_candidates = [config["primary"]] + config.get("fallbacks", [])

    for api_path in api_candidates:
        try:
            func = _resolve_function(ak, api_path)
            result = func(**merged_kwargs)
            logger.debug(f"akshare 接口 {api_path} 调用成功")
            return result
        except AttributeError as e:
            all_tried.append({"api": api_path, "error": f"接口不存在: {e}"})
            logger.warning(f"akshare 接口 {api_path} 不存在: {e}")
        except TypeError as e:
            all_tried.append({"api": api_path, "error": f"参数错误: {e}"})
            logger.warning(f"akshare 接口 {api_path} 参数错误: {e}")
        except Exception as e:
            all_tried.append({"api": api_path, "error": str(e)})
            logger.warning(f"akshare 接口 {api_path} 调用失败: {e}")

    # 所有接口都失败
    error_lines = [f"akshare 数据采集失败 [{config['description']}]", "尝试过的接口:"]
    for tried in all_tried:
        error_lines.append(f"  - {tried['api']}: {tried['error']}")
    error_lines += [
        "\n建议排查:",
        "  1. 运行 pip install akshare --upgrade 更新到最新版本",
        "  2. 查阅官方文档: https://akshare.akfamily.xyz/",
        "  3. 运行 python scripts/check_akshare.py 检查接口可用性",
        "  4. 如接口已变更，请更新 backend/utils/api_compat.py 中的映射表",
    ]
    raise AkshareAPIError("\n".join(error_lines))
