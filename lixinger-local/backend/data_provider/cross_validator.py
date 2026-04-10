"""
多数据源交叉校验引擎

对同一指标的多源数据进行比较校验:
- 数值偏差阈值检查 (如收盘价偏差 > 0.5% 则报警)
- 多数一致性投票 (3源中2源一致则采信)
- 时间戳对齐校验
- 返回校验报告: 一致性评分、异常源标记、推荐采用值

用法:
    validator = CrossValidator()
    result = validator.validate_daily_data({
        "source_a": df_a,
        "source_b": df_b,
        "source_c": df_c,
    })
    best_df = result.best_dataframe
"""
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class ValidationReport:
    """校验报告"""
    # 总体结果
    is_consistent: bool = True          # 数据是否一致
    consistency_score: float = 1.0       # 一致性评分 (0-1)
    source_count: int = 0               # 参与校验的数据源数
    best_source: str = ""               # 推荐的最佳数据源
    best_dataframe: Optional[pd.DataFrame] = None  # 推荐的 DataFrame

    # 各数据源的详细信息
    source_details: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # 发现的异常
    anomalies: List[Dict[str, Any]] = field(default_factory=list)

    # 融合后的数据 (多数一致值)
    merged_dataframe: Optional[pd.DataFrame] = None

    def to_dict(self) -> Dict[str, Any]:
        """转为可序列化的字典"""
        return {
            "is_consistent": self.is_consistent,
            "consistency_score": round(self.consistency_score, 4),
            "source_count": self.source_count,
            "best_source": self.best_source,
            "anomalies_count": len(self.anomalies),
            "anomalies": self.anomalies[:10],  # 最多展示 10 条
            "source_details": self.source_details,
        }


class CrossValidator:
    """
    多数据源交叉校验器

    支持的校验策略:
    1. 数值偏差阈值检查 — 同一日期/字段的值，如果偏差超过阈值则标记
    2. 多数一致性投票 — 3 源中 2 源一致则采信
    3. 时间戳对齐校验 — 检查各源的日期覆盖范围
    """

    def __init__(
        self,
        price_tolerance: float = 0.005,    # 价格偏差容忍度 (0.5%)
        volume_tolerance: float = 0.05,     # 成交量偏差容忍度 (5%)
        pct_chg_tolerance: float = 0.01,    # 涨跌幅偏差容忍度 (绝对值 1%)
    ):
        self.price_tolerance = price_tolerance
        self.volume_tolerance = volume_tolerance
        self.pct_chg_tolerance = pct_chg_tolerance

        # 各字段的容忍度配置
        self._field_tolerances = {
            "open": price_tolerance,
            "high": price_tolerance,
            "low": price_tolerance,
            "close": price_tolerance,
            "volume": volume_tolerance,
            "amount": volume_tolerance,
            "pct_chg": pct_chg_tolerance,
        }

    def validate_daily_data(
        self,
        source_data: Dict[str, pd.DataFrame],
    ) -> ValidationReport:
        """
        校验多源日K线数据。

        :param source_data: {source_name: DataFrame} 多源数据
        :return: ValidationReport
        """
        report = ValidationReport()
        report.source_count = len(source_data)

        if not source_data:
            report.is_consistent = False
            report.consistency_score = 0.0
            return report

        if len(source_data) == 1:
            # 只有一个数据源，无法校验
            source_name = next(iter(source_data))
            df = source_data[source_name]
            report.best_source = source_name
            report.best_dataframe = df
            report.merged_dataframe = df
            report.source_details[source_name] = {
                "rows": len(df),
                "status": "only_source",
            }
            return report

        # 过滤有效数据
        valid_sources = {}
        for name, df in source_data.items():
            if df is not None and not df.empty and "date" in df.columns:
                # 确保 date 列为字符串
                df = df.copy()
                df["date"] = df["date"].astype(str)
                valid_sources[name] = df
                report.source_details[name] = {
                    "rows": len(df),
                    "date_range": f"{df['date'].min()} ~ {df['date'].max()}",
                    "status": "valid",
                }
            else:
                report.source_details[name] = {
                    "rows": 0,
                    "status": "empty_or_invalid",
                }

        if len(valid_sources) < 2:
            # 有效数据源不足2个
            if valid_sources:
                best_name = next(iter(valid_sources))
                report.best_source = best_name
                report.best_dataframe = valid_sources[best_name]
                report.merged_dataframe = valid_sources[best_name]
            report.is_consistent = len(valid_sources) <= 1
            report.consistency_score = 1.0 if len(valid_sources) <= 1 else 0.5
            return report

        # 交叉校验
        anomalies = []
        match_counts = {name: 0 for name in valid_sources}
        total_comparisons = 0

        # 收集所有日期
        all_dates = set()
        for df in valid_sources.values():
            all_dates.update(df["date"].unique())

        # 逐日逐字段比较
        compare_fields = ["close", "open", "high", "low", "volume"]

        for date_str in sorted(all_dates):
            date_rows = {}
            for name, df in valid_sources.items():
                row = df[df["date"] == date_str]
                if not row.empty:
                    date_rows[name] = row.iloc[0]

            if len(date_rows) < 2:
                continue

            for field_name in compare_fields:
                values = {}
                for name, row in date_rows.items():
                    val = row.get(field_name)
                    if val is not None and pd.notna(val):
                        try:
                            values[name] = float(val)
                        except (ValueError, TypeError):
                            continue

                if len(values) < 2:
                    continue

                total_comparisons += 1
                tolerance = self._field_tolerances.get(field_name, 0.01)

                # 计算中位数作为参考值
                vals = list(values.values())
                median_val = float(np.median(vals))

                if median_val == 0:
                    # 避免除以零
                    consistent_sources = [
                        n for n, v in values.items() if abs(v) < 0.01
                    ]
                else:
                    consistent_sources = [
                        n for n, v in values.items()
                        if abs(v - median_val) / abs(median_val) <= tolerance
                    ]

                for name in consistent_sources:
                    match_counts[name] += 1

                outlier_sources = [
                    n for n in values if n not in consistent_sources
                ]

                if outlier_sources:
                    anomalies.append({
                        "date": date_str,
                        "field": field_name,
                        "outlier_sources": outlier_sources,
                        "values": {n: round(v, 4) for n, v in values.items()},
                        "median": round(median_val, 4),
                    })

        # 计算一致性评分
        # 公式: 各源在所有(日期×字段)比较中与中位数一致的比例
        # total_matches: 所有源中匹配中位数的总计数
        # max_possible: 总比较次数 × 源数量 (每次比较中每个源贡献1次机会)
        # 结果为 0-1 之间，1 表示所有源在所有比较中完全一致
        if total_comparisons > 0:
            total_matches = sum(match_counts.values())
            max_possible = total_comparisons * len(valid_sources)
            report.consistency_score = total_matches / max_possible if max_possible > 0 else 0
        else:
            report.consistency_score = 1.0

        report.anomalies = anomalies
        report.is_consistent = report.consistency_score >= 0.95

        # 选择最佳数据源: 匹配数最多 + 数据行数最多
        best_source = max(
            valid_sources.keys(),
            key=lambda n: (match_counts.get(n, 0), len(valid_sources[n])),
        )
        report.best_source = best_source
        report.best_dataframe = valid_sources[best_source]

        # 更新 source_details
        for name in valid_sources:
            report.source_details[name]["match_count"] = match_counts.get(name, 0)
            report.source_details[name]["is_best"] = (name == best_source)

        # 生成融合数据 (取中位数)
        report.merged_dataframe = self._merge_by_median(valid_sources)

        if anomalies:
            logger.warning(
                f"[CrossValidator] 发现 {len(anomalies)} 个数据差异, "
                f"一致性评分: {report.consistency_score:.4f}, "
                f"最佳源: {best_source}"
            )
        else:
            logger.info(
                f"[CrossValidator] 多源数据一致, "
                f"评分: {report.consistency_score:.4f}, "
                f"最佳源: {best_source}"
            )

        return report

    def _merge_by_median(
        self,
        source_data: Dict[str, pd.DataFrame],
    ) -> pd.DataFrame:
        """
        多源数据融合: 对每个日期的每个字段取中位数。

        :param source_data: {source_name: DataFrame}
        :return: 融合后的 DataFrame
        """
        if not source_data:
            return pd.DataFrame()

        # 以第一个数据源为基础
        base_name = next(iter(source_data))
        base_df = source_data[base_name].copy()

        if len(source_data) == 1:
            return base_df

        numeric_fields = ["open", "high", "low", "close", "volume", "amount", "pct_chg"]

        # 收集所有日期
        all_dates = set()
        for df in source_data.values():
            if "date" in df.columns:
                all_dates.update(df["date"].unique())

        merged_rows = []
        for date_str in sorted(all_dates):
            row_data = {"date": date_str}
            for field_name in numeric_fields:
                values = []
                for df in source_data.values():
                    date_row = df[df["date"] == date_str]
                    if not date_row.empty:
                        val = date_row.iloc[0].get(field_name)
                        if val is not None and pd.notna(val):
                            try:
                                values.append(float(val))
                            except (ValueError, TypeError):
                                continue
                if values:
                    row_data[field_name] = float(np.median(values))
                else:
                    row_data[field_name] = None
            merged_rows.append(row_data)

        if merged_rows:
            return pd.DataFrame(merged_rows)
        return base_df

    def validate_single_field(
        self,
        source_values: Dict[str, float],
        tolerance: float = 0.005,
    ) -> Tuple[float, List[str]]:
        """
        校验单个字段的多源值。

        :param source_values: {source_name: value}
        :param tolerance: 容忍偏差比例
        :return: (推荐值, 异常源列表)
        """
        if not source_values:
            return 0.0, []

        if len(source_values) == 1:
            return next(iter(source_values.values())), []

        vals = list(source_values.values())
        median_val = float(np.median(vals))

        if median_val == 0:
            outliers = [n for n, v in source_values.items() if abs(v) > 0.01]
        else:
            outliers = [
                n for n, v in source_values.items()
                if abs(v - median_val) / abs(median_val) > tolerance
            ]

        return median_val, outliers
