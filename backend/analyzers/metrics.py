"""
财务指标计算模块

提供从原始财务数据计算各类衍生指标的函数。
"""
import logging
from typing import List, Dict, Optional

from utils.logger import get_logger

logger = get_logger(__name__)


def calc_growth_rate(values: List[Optional[float]]) -> Optional[float]:
    """
    计算复合增长率（CAGR）。

    :param values: 按时间顺序排列的数值列表（最旧在前）
    :return: 年化复合增长率（百分比）
    """
    cleaned = [v for v in values if v is not None and v != 0]
    if len(cleaned) < 2:
        return None
    years = len(cleaned) - 1
    if cleaned[0] <= 0:
        return None
    try:
        rate = (cleaned[-1] / cleaned[0]) ** (1 / years) - 1
        return round(rate * 100, 4)
    except (ZeroDivisionError, ValueError):
        return None


def calc_avg(values: List[Optional[float]]) -> Optional[float]:
    """计算平均值"""
    cleaned = [v for v in values if v is not None]
    if not cleaned:
        return None
    return round(sum(cleaned) / len(cleaned), 4)


def calc_percentile(value: float, history: List[float]) -> Optional[float]:
    """
    计算当前值在历史数据中的分位数（百分比）。

    :param value: 当前值
    :param history: 历史数据序列
    :return: 分位数 0-100
    """
    if not history or value is None:
        return None
    below = sum(1 for v in history if v <= value)
    return round(below / len(history) * 100, 2)


def calc_quantile_levels(history: List[float], levels: List[float] = None) -> Dict[str, float]:
    """
    计算历史序列的分位数值。

    :param history: 历史数据
    :param levels: 分位数级别（0-1），默认 [0.25, 0.5, 0.75]
    :return: {"p25": ..., "p50": ..., "p75": ...}
    """
    if levels is None:
        levels = [0.25, 0.5, 0.75]
    if not history:
        return {}
    sorted_h = sorted(h for h in history if h is not None)
    n = len(sorted_h)
    result = {}
    for level in levels:
        idx = int(level * n)
        idx = min(idx, n - 1)
        key = f"p{int(level * 100)}"
        result[key] = sorted_h[idx]
    return result
