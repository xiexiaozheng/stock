"""
内置指标示例：历史 PE 百分位指标

本模块展示如何通过继承 BaseIndicator 基类，利用 DataReader 接口
加载数据、计算并返回结果，是量化指标扩展的标准范例。

使用方式::

    from analyzers.indicator_framework import IndicatorRegistry
    registry = IndicatorRegistry(db_session)

    # 计算 000001.SZ 近 5 年 PE 百分位
    result = registry.compute("pe_percentile", ts_code="000001.SZ", years=5)
    # 返回示例:
    # {
    #     "ts_code": "000001.SZ",
    #     "current_pe": 8.52,
    #     "percentile": 23.5,          # 当前PE处于历史23.5%分位
    #     "pe_median": 9.88,           # 历史中位数
    #     "pe_p25": 7.62,              # 25%分位数
    #     "pe_p75": 12.33,             # 75%分位数
    #     "pe_min": 5.21,
    #     "pe_max": 18.76,
    #     "data_points": 1216,         # 数据点数
    #     "valuation_level": "低估",   # 估值水平判断
    # }

扩展建议：
- 可参照此模式实现 PB 百分位、PS 百分位、股息率百分位
- 可实现 DCF 模型参数估计器（继承 BaseIndicator）
- 可实现宏观经济关联指标（如 PE 与 M2 增速的相关性）
"""
from datetime import datetime, timedelta
from typing import Any, Dict

import numpy as np

from analyzers.indicator_framework import BaseIndicator, IndicatorRegistry


@IndicatorRegistry.register
class PEPercentileIndicator(BaseIndicator):
    """
    历史 PE-TTM 百分位指标

    通过加载指定股票近 N 年的 PE-TTM 日度数据，计算当前 PE 在历史中的分位数，
    辅助判断当前估值水平是否合理。

    参数：
        years (int): 回溯年数，默认 5 年
    """

    name = "pe_percentile"
    description = "计算历史 PE-TTM 百分位，判断当前估值所处历史区间"

    def compute(self, ts_code: str, **kwargs) -> Dict[str, Any]:
        """
        计算指定股票的历史 PE 百分位。

        :param ts_code: 股票代码（如 000001.SZ）
        :param years: 回溯年数，默认 5
        :return: 包含 PE 百分位、分位数值和估值水平的字典
        """
        years = kwargs.get("years", 5)

        # 1. 通过 DataReader 接口加载数据
        start_date = (datetime.today() - timedelta(days=365 * years)).strftime("%Y-%m-%d")
        df = self.reader.read_daily_market(
            ts_code,
            start_date=start_date,
            fields=["pe_ttm"],
        )

        if df.empty or "pe_ttm" not in df.columns:
            return {
                "ts_code": ts_code,
                "error": "无可用的 PE-TTM 数据",
                "data_points": 0,
            }

        # 2. 清洗数据：去除 NaN 和异常值（负数PE通常代表亏损，单独标记）
        pe_series = df["pe_ttm"].dropna()
        pe_positive = pe_series[pe_series > 0]

        if pe_positive.empty:
            return {
                "ts_code": ts_code,
                "error": "无有效的正数 PE-TTM 数据（可能持续亏损）",
                "data_points": len(pe_series),
                "negative_pe_ratio": float(
                    (pe_series < 0).sum() / len(pe_series) * 100
                ) if len(pe_series) > 0 else 0.0,
            }

        # 3. 获取当前 PE（最新一条有效数据）
        current_pe = float(pe_positive.iloc[-1])

        # 4. 计算百分位
        pe_values = pe_positive.values
        percentile = float(np.sum(pe_values <= current_pe) / len(pe_values) * 100)

        # 5. 计算分位数统计
        pe_min = float(np.min(pe_values))
        pe_max = float(np.max(pe_values))
        pe_median = float(np.median(pe_values))
        pe_p25 = float(np.percentile(pe_values, 25))
        pe_p75 = float(np.percentile(pe_values, 75))

        # 6. 估值水平判断
        if percentile <= 20:
            valuation_level = "极度低估"
        elif percentile <= 40:
            valuation_level = "低估"
        elif percentile <= 60:
            valuation_level = "合理"
        elif percentile <= 80:
            valuation_level = "偏高"
        else:
            valuation_level = "极度高估"

        return {
            "ts_code": ts_code,
            "current_pe": round(current_pe, 2),
            "percentile": round(percentile, 2),
            "pe_median": round(pe_median, 2),
            "pe_p25": round(pe_p25, 2),
            "pe_p75": round(pe_p75, 2),
            "pe_min": round(pe_min, 2),
            "pe_max": round(pe_max, 2),
            "data_points": len(pe_values),
            "valuation_level": valuation_level,
            "years": years,
        }


@IndicatorRegistry.register
class PBPercentileIndicator(BaseIndicator):
    """
    历史 PB 百分位指标

    与 PE 百分位类似，计算市净率在历史中的分位数。
    适用于银行、地产等重资产行业的估值分析。
    """

    name = "pb_percentile"
    description = "计算历史 PB 百分位，适用于重资产行业估值分析"

    def compute(self, ts_code: str, **kwargs) -> Dict[str, Any]:
        years = kwargs.get("years", 5)
        start_date = (datetime.today() - timedelta(days=365 * years)).strftime("%Y-%m-%d")
        df = self.reader.read_daily_market(
            ts_code,
            start_date=start_date,
            fields=["pb"],
        )

        if df.empty or "pb" not in df.columns:
            return {"ts_code": ts_code, "error": "无可用的 PB 数据", "data_points": 0}

        pb_series = df["pb"].dropna()
        pb_positive = pb_series[pb_series > 0]

        if pb_positive.empty:
            return {"ts_code": ts_code, "error": "无有效的正数 PB 数据", "data_points": 0}

        current_pb = float(pb_positive.iloc[-1])
        pb_values = pb_positive.values
        percentile = float(np.sum(pb_values <= current_pb) / len(pb_values) * 100)

        if percentile <= 20:
            level = "极度低估"
        elif percentile <= 40:
            level = "低估"
        elif percentile <= 60:
            level = "合理"
        elif percentile <= 80:
            level = "偏高"
        else:
            level = "极度高估"

        return {
            "ts_code": ts_code,
            "current_pb": round(current_pb, 2),
            "percentile": round(percentile, 2),
            "pb_median": round(float(np.median(pb_values)), 2),
            "pb_p25": round(float(np.percentile(pb_values, 25)), 2),
            "pb_p75": round(float(np.percentile(pb_values, 75)), 2),
            "pb_min": round(float(np.min(pb_values)), 2),
            "pb_max": round(float(np.max(pb_values)), 2),
            "data_points": len(pb_values),
            "valuation_level": level,
            "years": years,
        }


@IndicatorRegistry.register
class DividendYieldPercentileIndicator(BaseIndicator):
    """
    历史股息率百分位指标

    计算近12月股息率在历史中的分位数，适用于高股息策略。
    """

    name = "dv_percentile"
    description = "计算历史股息率百分位，适用于高股息策略"

    def compute(self, ts_code: str, **kwargs) -> Dict[str, Any]:
        years = kwargs.get("years", 5)
        start_date = (datetime.today() - timedelta(days=365 * years)).strftime("%Y-%m-%d")
        df = self.reader.read_daily_market(
            ts_code,
            start_date=start_date,
            fields=["dv_ttm"],
        )

        if df.empty or "dv_ttm" not in df.columns:
            return {"ts_code": ts_code, "error": "无可用的股息率数据", "data_points": 0}

        dv_series = df["dv_ttm"].dropna()
        dv_positive = dv_series[dv_series > 0]

        if dv_positive.empty:
            return {"ts_code": ts_code, "error": "无有效的正股息率数据", "data_points": 0}

        current_dv = float(dv_positive.iloc[-1])
        dv_values = dv_positive.values
        percentile = float(np.sum(dv_values <= current_dv) / len(dv_values) * 100)

        return {
            "ts_code": ts_code,
            "current_dv": round(current_dv, 4),
            "percentile": round(percentile, 2),
            "dv_median": round(float(np.median(dv_values)), 4),
            "dv_max": round(float(np.max(dv_values)), 4),
            "data_points": len(dv_values),
            "years": years,
        }
