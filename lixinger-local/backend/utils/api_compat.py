"""
akshare 接口兼容层 — 多信源版

由于 akshare 接口更新频繁，所有 akshare 调用都通过此模块统一入口。
当接口变更时，只需修改此文件的映射表即可，无需改动业务代码。

增强:
- 接口映射表扩展: 每个 API key 列出所有 akshare 支持的信源接口
- 智能错误分类: 区分 API 语法错误 vs 反爬虫错误
- API 语法错误时停止重试
- 反爬虫错误时自适应调频
- 参数转换规则可配置: 按接口路径分别做代码格式转换
"""
import logging
from typing import Any

logger = logging.getLogger(__name__)


class AkshareAPIError(Exception):
    """akshare 接口调用失败异常"""
    pass


# =====================================================================
# 股票代码格式转换工具函数
# =====================================================================

def _strip_exchange_prefix(code: str) -> str:
    """去除已有的交易所前缀，返回6位纯数字代码"""
    code = str(code).strip()
    # 处理 '000001.SZ' 格式
    if "." in code:
        code = code.split(".")[0]
    # 处理 'sh000001' / 'sz000001' / 'SH600519' 格式
    upper = code.upper()
    for prefix in ("SH", "SZ", "BJ"):
        if upper.startswith(prefix):
            code = code[2:]
            break
    return code.zfill(6)


def to_sina_code(code: str) -> str:
    """
    将股票代码转换为新浪财经格式 (小写前缀)。

    '000011' → 'sz000011'
    '600519' → 'sh600519'
    'SH600519' → 'sh600519'
    '600519.SH' → 'sh600519'
    """
    pure = _strip_exchange_prefix(code)
    prefix = "sh" if pure.startswith(("6", "9")) else "sz"
    return f"{prefix}{pure}"


def to_em_code(code: str) -> str:
    """
    将股票代码转换为东方财富 EM 格式 (大写前缀)。

    '000011' → 'SZ000011'
    '600519' → 'SH600519'
    'sh600519' → 'SH600519'
    '600519.SH' → 'SH600519'
    """
    pure = _strip_exchange_prefix(code)
    prefix = "SH" if pure.startswith(("6", "9")) else "SZ"
    return f"{prefix}{pure}"


# =====================================================================
# 接口映射配置
# =====================================================================

# 接口映射配置：主接口 + 备选接口列表 (列出 akshare 支持的所有信源)
#
# 字段说明:
#   primary          主接口 API 路径 (ak.xxx)
#   fallbacks        备选接口列表，主接口失败时依次尝试
#   description      接口描述，用于错误信息
#   params           默认参数，与调用时传入的参数合并（调用方优先）
#   param_transforms 每个接口路径对应的参数转换规则，格式:
#                    {api_path: [(src_key, dst_key, transform_fn), ...]}
#                    - src_key: 合并后参数中的源键
#                    - dst_key: 转换后目标键（可与 src_key 相同）
#                    - transform_fn: 转换函数 (str) -> str；None 表示只做重命名
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
            "ak.stock_zh_a_daily",       # 新浪财经信源
            "ak.stock_zh_a_hist_tx",     # 腾讯财经信源 (如可用)
        ],
        "description": "获取日K线行情数据 (akshare 所有信源)",
        "params": {"adjust": "qfq"},
    },
    "financial_income": {
        # 新浪财报: stock_financial_report_sina(stock="sh600600", symbol="利润表")
        # 东财年报: stock_profit_sheet_by_yearly_em(symbol="SH600519")
        "primary": "ak.stock_financial_report_sina",
        "fallbacks": [
            "ak.stock_profit_sheet_by_yearly_em",
        ],
        "description": "获取利润表",
        # symbol 参数是新浪接口的报表类型 (中文枚举)
        # 对于 EM 接口，symbol 会被 param_transforms 覆盖为股票代码
        "params": {"symbol": "利润表"},
        "param_transforms": {
            # 新浪: stock="000011" → stock="sz000011"，symbol 保持"利润表"
            "ak.stock_financial_report_sina": [
                ("stock", "stock", to_sina_code),
            ],
            # 东财: stock="000011" → symbol="SZ000011"（覆盖掉"利润表"，EM 不需要报表类型参数）
            "ak.stock_profit_sheet_by_yearly_em": [
                ("stock", "symbol", to_em_code),
            ],
        },
    },
    "financial_balance": {
        # 新浪财报: stock_financial_report_sina(stock="sh600600", symbol="资产负债表")
        # 东财年报: stock_balance_sheet_by_yearly_em(symbol="SH600519")
        "primary": "ak.stock_financial_report_sina",
        "fallbacks": [
            "ak.stock_balance_sheet_by_yearly_em",
        ],
        "description": "获取资产负债表",
        "params": {"symbol": "资产负债表"},
        "param_transforms": {
            "ak.stock_financial_report_sina": [
                ("stock", "stock", to_sina_code),
            ],
            "ak.stock_balance_sheet_by_yearly_em": [
                ("stock", "symbol", to_em_code),
            ],
        },
    },
    "financial_cashflow": {
        # 新浪财报: stock_financial_report_sina(stock="sh600600", symbol="现金流量表")
        # 东财年报: stock_cash_flow_sheet_by_yearly_em(symbol="SH600519")
        "primary": "ak.stock_financial_report_sina",
        "fallbacks": [
            "ak.stock_cash_flow_sheet_by_yearly_em",
        ],
        "description": "获取现金流量表",
        "params": {"symbol": "现金流量表"},
        "param_transforms": {
            "ak.stock_financial_report_sina": [
                ("stock", "stock", to_sina_code),
            ],
            "ak.stock_cash_flow_sheet_by_yearly_em": [
                ("stock", "symbol", to_em_code),
            ],
        },
    },
    "valuation_indicator": {
        # stock_a_indicator_lg 已从 akshare 中移除 (文档中未找到)。
        # 暂无完全等价的替代接口能提供相同的历史 PE/PB 序列。
        # 留空 fallbacks，调用失败时会抛出清晰错误让上层降级处理。
        "primary": "ak.stock_a_indicator_lg",
        "fallbacks": [],
        "description": (
            "获取PE/PB/PS等估值指标历史序列 "
            "[注意: stock_a_indicator_lg 已不在 akshare 官方文档中，"
            "建议改用 BaostockFetcher 或 tushare daily_basic 替代]"
        ),
        "params": {},
    },
    "dividends": {
        # stock_dividents_cninfo 已从 akshare 中移除。
        # 替代接口: stock_fhps_detail_ths(symbol="603444") — 同花顺分红数据
        # 参数: symbol 为6位纯数字代码 (无交易所前缀)
        "primary": "ak.stock_fhps_detail_ths",
        "fallbacks": [],
        "description": "获取分红数据 (同花顺)",
        "params": {},
        # symbol 已由调用方传入 6 位纯数字代码，无需转换
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
        "description": "获取板块成分股 (支持行业名称或板块代码如 BK1027)",
        "params": {},
    },
    "stock_realtime": {
        "primary": "ak.stock_zh_a_spot_em",
        "fallbacks": [],
        "description": "获取A股实时行情（全市场）",
        "params": {},
    },
}


# =====================================================================
# 内部工具函数
# =====================================================================

def _resolve_function(module: Any, dotted_path: str):
    """将 'ak.stock_info_a_code_name' 解析为实际函数对象"""
    parts = dotted_path.split(".")
    obj = module
    for part in parts[1:]:  # 跳过 'ak'
        obj = getattr(obj, part)
    return obj


def _apply_param_transforms(
    api_path: str,
    call_kwargs: dict,
    param_transforms: dict,
) -> dict:
    """
    根据 param_transforms 配置对参数进行转换。

    param_transforms 格式:
        {
            "ak.some_interface": [
                (src_key, dst_key, transform_fn_or_None),
                ...
            ]
        }

    每条规则：
    - 若 src_key 在 call_kwargs 中，则：
        1. 对值应用 transform_fn (若为 None 则不变)
        2. 将结果写入 dst_key
        3. 若 dst_key != src_key，删除 src_key

    注意：dst_key 若已存在会被覆盖（用于 EM 接口中 symbol 的重用）。
    """
    transforms = param_transforms.get(api_path)
    if not transforms:
        return call_kwargs

    kw = dict(call_kwargs)
    for src_key, dst_key, transform_fn in transforms:
        if src_key not in kw:
            continue
        val = kw[src_key]
        if transform_fn is not None:
            val = transform_fn(val)
        if dst_key != src_key:
            del kw[src_key]
        kw[dst_key] = val
    return kw


def call_akshare(api_key: str, **kwargs) -> Any:
    """
    统一的 akshare 调用入口 (增强版: 智能错误分类 + 参数转换)。

    流程：
    1. 从 AKSHARE_API_MAP 获取主接口和备选接口
    2. 合并默认参数和传入参数（传入参数优先）
    3. 先尝试主接口
    4. 主接口失败时，依次尝试 fallbacks
    5. 每个接口调用前应用 param_transforms（代码格式转换等）
    6. 智能分类错误:
       - API 语法错误 (AttributeError, TypeError) → 停止当前候选，记录
       - 反爬虫错误 (403, 429) → 自适应调频后重试下一个
    7. 所有接口都失败时，抛出带有详细信息的 AkshareAPIError
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
    param_transforms = config.get("param_transforms", {})

    # 延迟导入错误分类器 (避免循环依赖: data_provider → utils → data_provider)
    # error_classifier 是独立模块，不依赖 api_compat，所以不会真正循环
    try:
        from data_provider.error_classifier import classify_error, ErrorCategory
    except ImportError:
        classify_error = None
        ErrorCategory = None

    for api_path in api_candidates:
        try:
            func = _resolve_function(ak, api_path)

            # 1. 先从合并参数复制一份
            call_kwargs = dict(merged_kwargs)

            # 2. 应用 param_transforms 中配置的转换规则
            call_kwargs = _apply_param_transforms(api_path, call_kwargs, param_transforms)

            # 3. 兼容旧逻辑: EM 接口若仍有 'stock' 参数且无转换规则，自动转为 symbol
            if "_em" in api_path and "stock" in call_kwargs and api_path not in param_transforms:
                call_kwargs["symbol"] = to_em_code(call_kwargs.pop("stock"))

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
