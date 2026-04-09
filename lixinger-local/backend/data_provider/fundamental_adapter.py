"""
基本面数据适配器 (Fail-Open 设计)

参考 ZhuLinsen/daily_stock_analysis data_provider/fundamental_adapter.py

设计原则:
  - 永不抛出异常给调用方
  - 部分数据允许缺失
  - Capability probing: 尝试多个接口候选，返回最佳可用

数据块:
  - growth: 营收同比增速、净利同比增速
  - earnings: ROE、净利率、EPS
  - institution: 机构持股
  - capital_flow: 资金流向
  - dragon_tiger: 龙虎榜

使用:
    adapter = FundamentalAdapter()
    bundle = adapter.get_fundamental_bundle('600519')
    # bundle['status'] == 'ok'|'partial'|'failed'
    # bundle['growth']['yoy_sales_growth'] == 15.3
"""
import logging
import re
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd

from data_provider.realtime_types import safe_float

logger = logging.getLogger(__name__)


# 分红方案关键词映射（参考 daily_stock_analysis）
_DIVIDEND_KEYWORD_MAP = {
    "per_share": [
        "每股派息", "每股现金红利", "每股分红", "每股派现",
        "派现(元/股)", "派息(元/股)", "税前派息(元/股)",
    ],
    "plan_text": [
        "分配方案", "分红方案", "实施方案", "派息方案",
        "方案", "预案", "方案说明",
    ],
    "ex_dividend_date": ["除权除息日", "除息日", "除权日"],
    "record_date": ["股权登记日", "登记日"],
    "announce_date": ["公告日期", "公告日", "实施公告日"],
    "report_date": ["报告期", "报告日期", "截止日期"],
}


def _pick_by_keywords(row: pd.Series, keywords: List[str]) -> Optional[Any]:
    """按关键词列表在行数据中查找第一个非空值"""
    for col in row.index:
        col_s = str(col)
        if any(k in col_s for k in keywords):
            val = row.get(col)
            if val is not None and str(val).strip() not in ("", "-", "nan", "None"):
                return val
    return None


def _parse_dividend_plan(plan_text: str) -> Optional[float]:
    """
    从中文分红方案解析每股现金分红。

    '每10股派发现金红利5.00元' → 0.5
    '10派3.5元' → 0.35
    """
    text = str(plan_text).strip()
    if not text:
        return None

    for pattern in (
        r"(?:每)?\s*10\s*股?\s*派(?:发)?\s*([0-9]+(?:\.[0-9]+)?)\s*元",
        r"10\s*派\s*([0-9]+(?:\.[0-9]+)?)\s*元",
    ):
        match = re.search(pattern, text)
        if match:
            per_10 = safe_float(match.group(1))
            if per_10 is not None and per_10 > 0:
                return per_10 / 10.0

    match_per = re.search(
        r"每\s*股\s*派(?:发)?\s*([0-9]+(?:\.[0-9]+)?)\s*元", text
    )
    if match_per:
        return safe_float(match_per.group(1))

    return None


class FundamentalAdapter:
    """
    基本面数据适配器

    Fail-open 设计: 永不抛出异常给调用方。
    每个数据块独立采集，部分失败不影响其他块。
    """

    def get_fundamental_bundle(
        self,
        stock_code: str,
        budget_seconds: float = 10.0,
    ) -> Dict[str, Any]:
        """
        聚合基本面数据块。

        :param stock_code: 6位股票代码
        :param budget_seconds: 最大采集时间预算 (秒)
        :return: {
            'status': 'ok'|'partial'|'failed',
            'growth': {...},
            'earnings': {...},
            'institution': {...},
            'source_chain': [...],
            'errors': [...]
        }
        """
        result = {
            "status": "failed",
            "growth": {},
            "earnings": {},
            "institution": {},
            "source_chain": [],
            "errors": [],
        }
        t0 = time.time()
        success_count = 0

        # ---- 增长指标 ----
        try:
            growth = self._fetch_growth(stock_code)
            if growth:
                result["growth"] = growth
                success_count += 1
                result["source_chain"].append({
                    "provider": "akshare_growth",
                    "result": "ok",
                    "duration_ms": int((time.time() - t0) * 1000),
                })
        except Exception as e:
            result["errors"].append(f"growth: {e}")
            result["source_chain"].append({
                "provider": "akshare_growth",
                "result": "failed",
                "error": str(e),
            })

        if time.time() - t0 > budget_seconds:
            result["status"] = "partial" if success_count > 0 else "failed"
            return result

        # ---- 盈利指标 ----
        try:
            earnings = self._fetch_earnings(stock_code)
            if earnings:
                result["earnings"] = earnings
                success_count += 1
                result["source_chain"].append({
                    "provider": "akshare_earnings",
                    "result": "ok",
                    "duration_ms": int((time.time() - t0) * 1000),
                })
        except Exception as e:
            result["errors"].append(f"earnings: {e}")

        if time.time() - t0 > budget_seconds:
            result["status"] = "partial" if success_count > 0 else "failed"
            return result

        # ---- 机构持股 ----
        try:
            institution = self._fetch_institution(stock_code)
            if institution:
                result["institution"] = institution
                success_count += 1
        except Exception as e:
            result["errors"].append(f"institution: {e}")

        # 设置最终状态
        if success_count == 3:
            result["status"] = "ok"
        elif success_count > 0:
            result["status"] = "partial"
        else:
            result["status"] = "failed"

        return result

    def _fetch_growth(self, stock_code: str) -> Dict[str, Any]:
        """
        获取增长指标 (营收同比/净利同比)。

        尝试多个 akshare 接口候选。
        """
        import akshare as ak

        growth = {}

        # 候选1: 业绩预告
        try:
            time.sleep(1)
            df = ak.stock_yjyg_em(date="")
            if df is not None and not df.empty:
                code_col = None
                for c in ("股票代码", "代码", "code"):
                    if c in df.columns:
                        code_col = c
                        break
                if code_col:
                    row = df[
                        df[code_col].astype(str).str.zfill(6) == stock_code
                    ]
                    if not row.empty:
                        r = row.iloc[0]
                        growth["yoy_sales_growth"] = safe_float(
                            r.get("营业收入同比增长", r.get("营业收入-同比增长"))
                        )
                        growth["yoy_profit_growth"] = safe_float(
                            r.get("净利润同比增长", r.get("净利润-同比增长"))
                        )
        except Exception as e:
            logger.debug(f"[FundamentalAdapter] 业绩预告接口失败: {e}")

        # 候选2: 利润表同比
        if not growth:
            try:
                time.sleep(1)
                df = ak.stock_profit_sheet_by_yearly_em(symbol=stock_code)
                if df is not None and not df.empty:
                    # 取最新两年计算同比
                    pass  # 复杂计算，暂留空
            except Exception as e:
                logger.debug(f"[FundamentalAdapter] 利润表接口失败: {e}")

        return growth

    def _fetch_earnings(self, stock_code: str) -> Dict[str, Any]:
        """
        获取盈利指标 (ROE, 净利率, EPS)。

        尝试 akshare 财务摘要接口。
        """
        import akshare as ak

        earnings = {}
        try:
            time.sleep(1)
            df = ak.stock_financial_abstract_sina(stock=stock_code)
            if df is not None and not df.empty:
                r = df.iloc[0]
                earnings["return_on_equity"] = safe_float(
                    _pick_by_keywords(r, ["净资产收益率", "ROE"])
                )
                earnings["net_profit_margin"] = safe_float(
                    _pick_by_keywords(r, ["净利率", "销售净利率"])
                )
                earnings["earnings_per_share"] = safe_float(
                    _pick_by_keywords(r, ["每股收益", "EPS"])
                )
        except Exception as e:
            logger.debug(f"[FundamentalAdapter] 财务摘要接口失败: {e}")

        return earnings

    def _fetch_institution(self, stock_code: str) -> Dict[str, Any]:
        """
        获取机构持股信息。

        尝试 akshare 机构持仓接口。
        """
        import akshare as ak

        institution = {}
        try:
            time.sleep(1)
            # 尝试获取机构持股数据
            df = ak.stock_institute_hold_detail(
                stock=stock_code,
                quarter=self._latest_quarter(),
            )
            if df is not None and not df.empty:
                institution["institution_count"] = len(df)
                shares_col = None
                for c in ("持股数量", "持股数", "持仓数量"):
                    if c in df.columns:
                        shares_col = c
                        break
                if shares_col:
                    institution["total_shares"] = safe_float(
                        pd.to_numeric(df[shares_col], errors="coerce").sum()
                    )
        except Exception as e:
            logger.debug(f"[FundamentalAdapter] 机构持股接口失败: {e}")

        return institution

    @staticmethod
    def _latest_quarter() -> str:
        """返回最近的季度报告期 (YYYYMMDD 格式)"""
        today = datetime.today()
        year = today.year
        month = today.month

        if month >= 10:
            return f"{year}0930"
        elif month >= 7:
            return f"{year}0630"
        elif month >= 4:
            return f"{year}0331"
        else:
            return f"{year - 1}1231"

    # ---- 资金流向 ----

    def get_capital_flow(self, stock_code: str) -> Dict[str, Any]:
        """
        获取资金流向数据。

        Fail-open: 返回空字典而非抛异常。
        """
        try:
            import akshare as ak
            time.sleep(1)
            df = ak.stock_individual_fund_flow(stock=stock_code, market="")
            if df is not None and not df.empty:
                r = df.iloc[0]
                return {
                    "net_inflow": safe_float(
                        r.get("主力净流入-净额", r.get("净流入"))
                    ),
                    "super_large_inflow": safe_float(
                        r.get("超大单净流入-净额")
                    ),
                    "large_inflow": safe_float(
                        r.get("大单净流入-净额")
                    ),
                    "medium_inflow": safe_float(
                        r.get("中单净流入-净额")
                    ),
                    "small_inflow": safe_float(
                        r.get("小单净流入-净额")
                    ),
                }
        except Exception as e:
            logger.debug(f"[FundamentalAdapter] 资金流向接口失败: {e}")
        return {}

    # ---- 龙虎榜 ----

    def get_dragon_tiger_flag(self, stock_code: str) -> Dict[str, Any]:
        """
        检查是否上龙虎榜。

        Fail-open: 返回空字典而非抛异常。
        """
        try:
            import akshare as ak
            time.sleep(1)
            today = datetime.today().strftime("%Y%m%d")
            df = ak.stock_lhb_detail_em(
                start_date=(datetime.today() - timedelta(days=30)).strftime("%Y%m%d"),
                end_date=today,
            )
            if df is not None and not df.empty:
                code_col = None
                for c in ("代码", "股票代码"):
                    if c in df.columns:
                        code_col = c
                        break
                if code_col:
                    matched = df[
                        df[code_col].astype(str).str.zfill(6) == stock_code
                    ]
                    return {
                        "is_on_list": len(matched) > 0,
                        "recent_count": len(matched),
                    }
        except Exception as e:
            logger.debug(f"[FundamentalAdapter] 龙虎榜接口失败: {e}")
        return {}
