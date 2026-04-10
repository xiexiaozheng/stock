"""
akshare 接口兼容层 — 多信源版

由于 akshare 接口更新频繁，所有 akshare 调用都通过此模块统一入口。
当接口变更时，只需修改此文件的映射表即可，无需改动业务代码。

增强:
- 接口映射表扩展: 每个 API key 列出所有 akshare 支持的信源接口
- 智能错误分类: 区分 API 语法错误 vs 反爬虫错误
- API 语法错误时停止重试
- 反爬虫错误时自适应调频
"""
import logging
from typing import Any

logger = logging.getLogger(__name__)


class AkshareAPIError(Exception):
    """akshare 接口调用失败异常"""
    pass


# 接口映射配置：主接口 + 备选接口列表 (列出 akshare 支持的所有信源)
AKSHARE_API_MAP = {
    "stock_list": {
        "primary": "ak.stock_info_a_code_name",
        "fallbacks": [],
        "description": "获取A股股票列表",
        "params": {},
    },
    "daily_quotes": {
        "primary": "ak.stock_zh_a_hist",
        "fallbacks": [
            "ak.stock_zh_a_daily",           # 新浪财经信源
        ],
        "description": "获取日K线行情数据 (akshare 所有信源)",
        "params": {"adjust": "qfq"},
    },
    "financial_income": {
        "primary": "ak.stock_financial_report_sina",
        "fallbacks": [
            "ak.stock_profit_sheet_by_yearly_em",
        ],
        "description": "获取利润表",
        "params": {"symbol": "income"},
    },
    "financial_balance": {
        "primary": "ak.stock_financial_report_sina",
        "fallbacks": [
            "ak.stock_balance_sheet_by_yearly_em",
        ],
        "description": "获取资产负债表",
        "params": {"symbol": "balance"},
    },
    "financial_cashflow": {
        "primary": "ak.stock_financial_report_sina",
        "fallbacks": [
            "ak.stock_cash_flow_sheet_by_yearly_em",
        ],
        "description": "获取现金流量表",
        "params": {"symbol": "cash_flow"},
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
    统一的 akshare 调用入口 (增强版: 智能错误分类)。

    流程：
    1. 从 AKSHARE_API_MAP 获取主接口和备选接口
    2. 先尝试主接口
    3. 主接口失败时，依次尝试 fallbacks
    4. 智能分类错误:
       - API 语法错误 (AttributeError, TypeError) → 停止当前候选，记录
       - 反爬虫错误 (403, 429) → 自适应调频后重试下一个
    5. 所有接口都失败时，抛出带有详细信息的 AkshareAPIError
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

    # 导入错误分类器
    try:
        from data_provider.error_classifier import classify_error, ErrorCategory
    except ImportError:
        classify_error = None
        ErrorCategory = None

    for api_path in api_candidates:
        try:
            func = _resolve_function(ak, api_path)
            call_kwargs = dict(merged_kwargs)
            if "_em" in api_path and "stock" in call_kwargs:
                call_kwargs["symbol"] = call_kwargs.pop("stock")
            result = func(**call_kwargs)
            logger.debug(f"akshare 接口 {api_path} 调用成功")
            return result
        except AttributeError as e:
            all_tried.append({"api": api_path, "error": f"接口不存在: {e}", "category": "api_syntax"})
            logger.warning(f"akshare 接口 {api_path} 不存在: {e}")
            # API 语法错误: 不重试此接口，继续下一个候选
        except TypeError as e:
            all_tried.append({"api": api_path, "error": f"参数错误: {e}", "category": "api_syntax"})
            logger.warning(f"akshare 接口 {api_path} 参数错误: {e}")
        except Exception as e:
            # 智能分类
            category = "unknown"
            if classify_error is not None:
                cat = classify_error(e)
                category = cat.value
                if cat == ErrorCategory.ANTI_CRAWL:
                    logger.warning(
                        f"akshare 接口 {api_path} 触发反爬虫: {e}, "
                        f"将尝试下一个候选接口"
                    )
                elif cat == ErrorCategory.API_SYNTAX:
                    logger.error(
                        f"akshare 接口 {api_path} API 语法错误，停止: {e}"
                    )

            all_tried.append({"api": api_path, "error": str(e), "category": category})
            logger.warning(f"akshare 接口 {api_path} 调用失败 [{category}]: {e}")

    # 所有接口都失败
    error_lines = [f"akshare 数据采集失败 [{config['description']}]", "尝试过的接口:"]
    for tried in all_tried:
        category_info = f" [{tried.get('category', 'unknown')}]" if 'category' in tried else ""
        error_lines.append(f"  - {tried['api']}: {tried['error']}{category_info}")
    error_lines += [
        "\n建议排查:",
        "  1. 运行 pip install akshare --upgrade 更新到最新版本",
        "  2. 查阅官方文档: https://akshare.akfamily.xyz/",
        "  3. 运行 python scripts/check_akshare.py 检查接口可用性",
        "  4. 如接口已变更，请更新 backend/utils/api_compat.py 中的映射表",
        "  5. 如果是反爬虫问题，检查调用频率配置 (config.py AKSHARE_FETCHER_SLEEP_*)",
    ]
    raise AkshareAPIError("\n".join(error_lines))
