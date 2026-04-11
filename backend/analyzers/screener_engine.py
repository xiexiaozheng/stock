"""
筛选器引擎

支持多条件组合筛选（AND/OR），多种时间窗口（最新/平均/连续N年）。
"""
import json
import logging
from datetime import datetime, date
from typing import List, Dict, Any, Optional

from sqlalchemy.orm import Session
from sqlalchemy import text

from analyzers.metrics import calc_avg, calc_growth_rate
from utils.logger import get_logger

logger = get_logger(__name__)

# ======================== 预设筛选模板 ========================

PRESET_SCREENERS = [
    {
        "id": "buffett",
        "name": "巴菲特选股",
        "description": "ROE连续5年>15%，毛利率>40%，负债率<60%",
        "conditions": {
            "logic": "AND",
            "conditions": [
                {"field": "roe", "operator": ">=", "value": 15, "period": "latest_annual", "consecutive_years": 5},
                {"field": "gross_margin", "operator": ">=", "value": 40, "period": "avg_3y"},
                {"field": "debt_ratio", "operator": "<", "value": 60},
            ],
        },
    },
    {
        "id": "value",
        "name": "低估值价值股",
        "description": "PE-TTM<15，PB<2，股息率>3%",
        "conditions": {
            "logic": "AND",
            "conditions": [
                {"field": "pe_ttm", "operator": "<", "value": 15},
                {"field": "pb", "operator": "<", "value": 2},
                {"field": "dividend_yield", "operator": ">=", "value": 3},
            ],
        },
    },
    {
        "id": "growth",
        "name": "高成长股",
        "description": "营收增长率>20%（3年复合），净利润增长率>25%",
        "conditions": {
            "logic": "AND",
            "conditions": [
                {"field": "revenue_growth", "operator": ">=", "value": 20, "period": "avg_3y"},
                {"field": "profit_growth", "operator": ">=", "value": 25, "period": "avg_3y"},
            ],
        },
    },
    {
        "id": "cashflow",
        "name": "现金流优秀",
        "description": "经营现金流/净利润>1，自由现金流转正",
        "conditions": {
            "logic": "AND",
            "conditions": [
                {"field": "ocf_to_profit", "operator": ">=", "value": 1},
                {"field": "free_cash_flow", "operator": ">", "value": 0},
            ],
        },
    },
    {
        "id": "new_stock",
        "name": "次新股掘金",
        "description": "上市<3年，ROE>12%，营收增长>15%",
        "conditions": {
            "logic": "AND",
            "conditions": [
                {"field": "listing_years", "operator": "<", "value": 3},
                {"field": "roe", "operator": ">", "value": 12, "period": "latest_annual"},
                {"field": "revenue_growth", "operator": ">", "value": 15, "period": "avg_3y"},
            ],
        },
    },
]

OPERATORS = {
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    "between": lambda a, b: b[0] <= a <= b[1],
    "in": lambda a, b: a in b,
    "not_in": lambda a, b: a not in b,
}


class ScreenerEngine:
    """筛选器引擎"""

    def __init__(self, db: Session):
        self.db = db

    def run(self, conditions: Dict, limit: int = 200) -> List[Dict]:
        """
        执行筛选，返回符合条件的股票列表。

        :param conditions: 筛选条件（参见模板格式）
        :param limit: 最大返回数量
        """
        # 1. 获取所有股票的基础数据
        candidates = self._get_all_candidates()
        logger.info(f"筛选候选股票数: {len(candidates)}")

        # 2. 逐条件过滤
        logic = conditions.get("logic", "AND").upper()
        cond_list = conditions.get("conditions", [])

        results = []
        for stock in candidates:
            try:
                if self._evaluate(stock, cond_list, logic):
                    results.append(stock)
            except Exception as e:
                logger.debug(f"筛选 {stock.get('stock_code')} 时出错: {e}")

        # 3. 排序
        sort_by = conditions.get("sort_by")
        sort_order = conditions.get("sort_order", "asc")
        if sort_by and sort_by in (results[0] if results else {}):
            results.sort(
                key=lambda x: (x.get(sort_by) is None, x.get(sort_by, 0)),
                reverse=(sort_order.lower() == "desc"),
            )

        return results[:limit]

    def _evaluate(self, stock: Dict, cond_list: List[Dict], logic: str) -> bool:
        """评估一只股票是否满足条件集"""
        if not cond_list:
            return True

        eval_results = [self._eval_single(stock, c) for c in cond_list]

        if logic == "AND":
            return all(eval_results)
        elif logic == "OR":
            return any(eval_results)
        return True

    def _eval_single(self, stock: Dict, condition: Dict) -> bool:
        """评估单条条件"""
        field = condition.get("field")
        operator = condition.get("operator", ">=")
        threshold = condition.get("value")
        period = condition.get("period", "latest_annual")
        consecutive_years = condition.get("consecutive_years")

        op_func = OPERATORS.get(operator)
        if op_func is None:
            logger.warning(f"未知的操作符: {operator}")
            return True

        value = self._get_field_value(stock, field, period, consecutive_years)
        if value is None:
            return False

        try:
            return op_func(value, threshold)
        except Exception:
            return False

    def _get_field_value(
        self,
        stock: Dict,
        field: str,
        period: str,
        consecutive_years: Optional[int],
    ) -> Optional[float]:
        """从股票数据中提取字段值，支持多种时间窗口"""
        # 直接字段（估值、市值等）
        if field in stock:
            return stock.get(field)

        financials = stock.get("_financials", [])
        if not financials:
            return None

        annual = [f for f in financials if f.get("report_type") == "annual"]
        annual.sort(key=lambda x: x.get("report_date", ""), reverse=True)

        if consecutive_years and annual:
            values = [f.get(field) for f in annual[:consecutive_years]]
            if len(values) < consecutive_years:
                return None
            threshold = stock.get("_threshold_for_consecutive")
            return min(v for v in values if v is not None) if all(v is not None for v in values) else None

        if period == "latest_annual":
            return annual[0].get(field) if annual else None
        elif period == "latest_quarter":
            quarters = [f for f in financials if f.get("report_type") != "annual"]
            quarters.sort(key=lambda x: x.get("report_date", ""), reverse=True)
            return quarters[0].get(field) if quarters else None
        elif period == "avg_3y":
            vals = [f.get(field) for f in annual[:3] if f.get(field) is not None]
            return calc_avg(vals)
        elif period == "avg_5y":
            vals = [f.get(field) for f in annual[:5] if f.get(field) is not None]
            return calc_avg(vals)
        elif period == "ttm":
            # TTM = 最近4个季度累计
            ttm_records = sorted(financials, key=lambda x: x.get("report_date", ""), reverse=True)[:4]
            vals = [f.get(field) for f in ttm_records if f.get(field) is not None]
            return sum(vals) if vals else None
        return None

    def _get_all_candidates(self) -> List[Dict]:
        """从数据库获取所有候选股票（含最新估值和财务数据）"""
        sql = text("""
            SELECT
                s.stock_code,
                s.stock_name,
                s.exchange,
                s.industry,
                s.listing_date,
                -- 最新估值
                v.pe_ttm,
                v.pb,
                v.ps_ttm,
                v.total_market_value,
                v.circulating_market_value,
                v.dividend_yield,
                -- 最新年报财务指标
                f.roe,
                f.roa,
                f.gross_margin,
                f.net_margin,
                f.debt_ratio,
                f.net_profit,
                f.operating_revenue AS revenue,
                f.operating_cash_flow,
                f.free_cash_flow
            FROM stocks s
            LEFT JOIN valuations v ON s.stock_code = v.stock_code
                AND v.trade_date = (
                    SELECT MAX(trade_date) FROM valuations WHERE stock_code = s.stock_code
                )
            LEFT JOIN financials f ON s.stock_code = f.stock_code
                AND f.report_type = 'annual'
                AND f.report_date = (
                    SELECT MAX(report_date) FROM financials
                    WHERE stock_code = s.stock_code AND report_type = 'annual'
                )
            WHERE s.is_active = 1
        """)
        rows = self.db.execute(sql).fetchall()
        keys = [
            "stock_code", "stock_name", "exchange", "industry", "listing_date",
            "pe_ttm", "pb", "ps_ttm", "total_market_value", "circulating_market_value",
            "dividend_yield", "roe", "roa", "gross_margin", "net_margin", "debt_ratio",
            "net_profit", "revenue", "operating_cash_flow", "free_cash_flow",
        ]
        candidates = []
        today = date.today()
        for row in rows:
            d = dict(zip(keys, row))
            # 计算上市年数
            if d.get("listing_date"):
                ld = d["listing_date"]
                if isinstance(ld, str):
                    try:
                        ld = datetime.strptime(ld, "%Y-%m-%d").date()
                    except Exception:
                        ld = None
                if ld:
                    d["listing_years"] = (today - ld).days / 365.25

            # 经营现金流/净利润比
            if d.get("operating_cash_flow") and d.get("net_profit") and d["net_profit"] != 0:
                d["ocf_to_profit"] = d["operating_cash_flow"] / d["net_profit"]

            # 获取历史财务数据（用于多年期条件）
            fin_sql = text("""
                SELECT report_type, report_date, roe, gross_margin, net_margin,
                       debt_ratio, net_profit, operating_revenue, operating_cash_flow, free_cash_flow
                FROM financials
                WHERE stock_code = :code
                ORDER BY report_date DESC
                LIMIT 20
            """)
            fin_rows = self.db.execute(fin_sql, {"code": d["stock_code"]}).fetchall()
            fin_keys = ["report_type", "report_date", "roe", "gross_margin", "net_margin",
                        "debt_ratio", "net_profit", "operating_revenue", "operating_cash_flow", "free_cash_flow"]
            d["_financials"] = [dict(zip(fin_keys, fr)) for fr in fin_rows]

            candidates.append(d)

        return candidates
