"""
akshare 数据采集模块

负责从 akshare 获取：股票列表、日K线行情、财务报表、估值指标、分红数据、行业板块数据
所有接口调用通过 api_compat.call_akshare() 统一入口，自动处理 fallback 和限流。
"""
import logging
import time
import random
import re
from datetime import datetime, date, timedelta
from typing import List, Optional, Dict, Any

import pandas as pd
from sqlalchemy.orm import Session

from collectors.base import BaseCollector
from models.stock import Stock, DailyQuote
from models.financial import Financial
from models.valuation import Valuation, Dividend
from models.screener import Industry, IndustryMember
from utils.api_compat import call_akshare, AkshareAPIError
from utils.logger import get_logger
from config import HISTORY_YEARS_QUOTES, HISTORY_YEARS_FINANCIALS, HISTORY_YEARS_VALUATIONS

logger = get_logger(__name__)


def _safe_float(val) -> Optional[float]:
    """安全转换为浮点数，失败返回 None"""
    try:
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return None
        return float(val)
    except (ValueError, TypeError):
        return None


def _safe_date(val) -> Optional[date]:
    """安全转换为 date 对象"""
    if val is None:
        return None
    if isinstance(val, date):
        return val
    if isinstance(val, str):
        for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d"):
            try:
                return datetime.strptime(val.strip(), fmt).date()
            except ValueError:
                continue
    return None


def _infer_exchange(code: str) -> str:
    """根据股票代码推断交易所"""
    if code.startswith(("60", "68")):
        return "SH"
    elif code.startswith(("00", "30")):
        return "SZ"
    elif code.startswith(("43", "83", "87", "88")):
        return "BJ"
    return "SZ"


class AkshareCollector(BaseCollector):
    """akshare 数据采集器"""

    # ======================== 股票列表 ========================

    def collect_stock_list(self) -> int:
        """采集全市场 A 股列表，写入 stocks 表"""
        logger.info("开始采集 A 股股票列表...")
        try:
            df = call_akshare("stock_list")
        except AkshareAPIError as e:
            logger.error(f"股票列表采集失败: {e}")
            return 0

        rows = []
        for _, row in df.iterrows():
            code = str(row.get("code", row.get("股票代码", ""))).strip().zfill(6)
            name = str(row.get("name", row.get("股票名称", ""))).strip()
            if not code or not name:
                continue
            rows.append({
                "stock_code": code,
                "stock_name": name,
                "exchange": _infer_exchange(code),
                "is_active": True,
            })

        if rows:
            count = self._upsert(Stock, rows, ["stock_code"])
            logger.info(f"股票列表采集完成，写入/更新 {len(rows)} 条")
            return len(rows)
        logger.warning("股票列表采集结果为空")
        return 0

    # ======================== 日K线行情 ========================

    def collect_daily_quotes(
        self,
        stock_code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> int:
        """
        采集指定股票日K线数据（增量更新）。

        :param stock_code: 6位股票代码
        :param start_date: 开始日期 YYYYMMDD，None 则从历史开始
        :param end_date: 结束日期 YYYYMMDD，None 则到今天
        :return: 写入行数
        """
        if start_date is None:
            cutoff = datetime.today() - timedelta(days=365 * HISTORY_YEARS_QUOTES)
            start_date = cutoff.strftime("%Y%m%d")
        if end_date is None:
            end_date = datetime.today().strftime("%Y%m%d")

        # 增量：找到已有数据的最新日期
        latest = (
            self.db.query(DailyQuote.trade_date)
            .filter(DailyQuote.stock_code == stock_code)
            .order_by(DailyQuote.trade_date.desc())
            .first()
        )
        if latest:
            latest_dt = latest[0]
            if isinstance(latest_dt, str):
                latest_dt = datetime.strptime(latest_dt, "%Y-%m-%d").date()
            incremental_start = (latest_dt + timedelta(days=1)).strftime("%Y%m%d")
            if incremental_start > end_date:
                logger.debug(f"{stock_code} 行情数据已是最新，跳过")
                return 0
            start_date = incremental_start

        self._rate_limit(0.5, 1.0)
        try:
            df = call_akshare(
                "daily_quotes",
                symbol=stock_code,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust="qfq",
            )
        except AkshareAPIError as e:
            logger.error(f"{stock_code} 行情采集失败: {e}")
            return 0

        if df is None or df.empty:
            return 0

        col_map = {
            "日期": "trade_date", "date": "trade_date",
            "开盘": "open", "open": "open",
            "最高": "high", "high": "high",
            "最低": "low", "low": "low",
            "收盘": "close", "close": "close",
            "成交量": "volume", "volume": "volume",
            "成交额": "amount", "amount": "amount",
            "换手率": "turnover_rate", "turnover_rate": "turnover_rate",
            "振幅": "amplitude", "amplitude": "amplitude",
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

        rows = []
        for _, row in df.iterrows():
            td = _safe_date(row.get("trade_date"))
            if td is None:
                continue
            rows.append({
                "stock_code": stock_code,
                "trade_date": td,
                "open": _safe_float(row.get("open")),
                "high": _safe_float(row.get("high")),
                "low": _safe_float(row.get("low")),
                "close": _safe_float(row.get("close")),
                "volume": int(row["volume"]) if pd.notna(row.get("volume")) else None,
                "amount": _safe_float(row.get("amount")),
                "turnover_rate": _safe_float(row.get("turnover_rate")),
                "amplitude": _safe_float(row.get("amplitude")),
            })

        if rows:
            self._upsert(DailyQuote, rows, ["stock_code", "trade_date"])
        return len(rows)

    # ======================== 财务报表 ========================

    def collect_financials(self, stock_code: str) -> int:
        """采集财务报表（利润表+资产负债表+现金流量表），合并写入 financials 表"""
        logger.info(f"采集 {stock_code} 财务报表...")

        # 组装财务数据字典 {report_date: {...}}
        data_map: Dict[str, Dict] = {}

        self._collect_income(stock_code, data_map)
        self._collect_balance(stock_code, data_map)
        self._collect_cashflow(stock_code, data_map)

        rows = []
        for report_date, fields in data_map.items():
            # 计算衍生指标
            fields.update(self._calc_derived_metrics(fields))
            fields["stock_code"] = stock_code
            fields["report_date"] = report_date
            rows.append(fields)

        if rows:
            self._upsert(Financial, rows, ["stock_code", "report_type", "report_date"])
        logger.info(f"{stock_code} 财务报表写入 {len(rows)} 期")
        return len(rows)

    def _collect_income(self, stock_code: str, data_map: Dict):
        """采集利润表"""
        self._rate_limit()
        try:
            # [需验证] 参数格式因版本而异
            # 备选1: ak.stock_financial_report_sina(stock=stock_code, symbol="income")
            # 备选2: ak.stock_profit_sheet_by_yearly_em(symbol=stock_code)
            df = call_akshare("financial_income", symbol=stock_code)
        except AkshareAPIError as e:
            logger.warning(f"{stock_code} 利润表采集失败: {e}")
            return

        if df is None or df.empty:
            return

        for _, row in df.iterrows():
            key, rt = self._parse_report_key(row)
            if key not in data_map:
                data_map[key] = {"report_type": rt}
            entry = data_map[key]
            entry["total_revenue"] = _safe_float(self._find_col(row, ["营业总收入", "total_revenue"]))
            entry["operating_revenue"] = _safe_float(self._find_col(row, ["营业收入", "operating_revenue"]))
            entry["operating_cost"] = _safe_float(self._find_col(row, ["营业总成本", "营业成本", "operating_cost"]))
            rev = entry.get("operating_revenue") or entry.get("total_revenue")
            cost = entry.get("operating_cost")
            entry["gross_profit"] = (rev - cost) if (rev and cost) else None
            entry["net_profit"] = _safe_float(self._find_col(row, ["净利润", "net_profit"]))
            entry["net_profit_deducted"] = _safe_float(
                self._find_col(row, ["扣除非经常性损益后的净利润", "net_profit_deducted"])
            )

    def _collect_balance(self, stock_code: str, data_map: Dict):
        """采集资产负债表"""
        self._rate_limit()
        try:
            df = call_akshare("financial_balance", symbol=stock_code)
        except AkshareAPIError as e:
            logger.warning(f"{stock_code} 资产负债表采集失败: {e}")
            return

        if df is None or df.empty:
            return

        for _, row in df.iterrows():
            key, rt = self._parse_report_key(row)
            if key not in data_map:
                data_map[key] = {"report_type": rt}
            entry = data_map[key]
            entry["total_assets"] = _safe_float(self._find_col(row, ["资产总计", "total_assets"]))
            entry["total_liabilities"] = _safe_float(self._find_col(row, ["负债合计", "total_liabilities"]))
            entry["total_equity"] = _safe_float(self._find_col(row, ["所有者权益合计", "归属于母公司所有者权益合计", "total_equity"]))
            entry["goodwill"] = _safe_float(self._find_col(row, ["商誉", "goodwill"]))

    def _collect_cashflow(self, stock_code: str, data_map: Dict):
        """采集现金流量表"""
        self._rate_limit()
        try:
            df = call_akshare("financial_cashflow", symbol=stock_code)
        except AkshareAPIError as e:
            logger.warning(f"{stock_code} 现金流量表采集失败: {e}")
            return

        if df is None or df.empty:
            return

        for _, row in df.iterrows():
            key, rt = self._parse_report_key(row)
            if key not in data_map:
                data_map[key] = {"report_type": rt}
            entry = data_map[key]
            entry["operating_cash_flow"] = _safe_float(
                self._find_col(row, ["经营活动产生的现金流量净额", "operating_cash_flow"])
            )
            entry["investing_cash_flow"] = _safe_float(
                self._find_col(row, ["投资活动产生的现金流量净额", "investing_cash_flow"])
            )
            entry["financing_cash_flow"] = _safe_float(
                self._find_col(row, ["筹资活动产生的现金流量净额", "financing_cash_flow"])
            )
            ocf = entry.get("operating_cash_flow")
            icf = entry.get("investing_cash_flow")
            if ocf is not None and icf is not None:
                entry["free_cash_flow"] = ocf + icf
            else:
                entry["free_cash_flow"] = None

    def _parse_report_key(self, row) -> tuple:
        """从行数据中解析报告期 key 和 report_type"""
        date_col = self._find_col(row, ["报告期", "report_date", "REPORT_DATE", "date"])
        if date_col:
            d = _safe_date(str(date_col))
            if d:
                month = d.month
                if month == 12:
                    rt = "annual"
                elif month == 3:
                    rt = "Q1"
                elif month == 6:
                    rt = "Q2"
                elif month == 9:
                    rt = "Q3"
                else:
                    rt = "annual"
                return str(d), rt
        return str(datetime.today().date()), "annual"

    @staticmethod
    def _find_col(row, candidates: List[str]):
        """在行数据中按候选列名查找值"""
        for c in candidates:
            if c in row.index and pd.notna(row[c]):
                return row[c]
        return None

    @staticmethod
    def _calc_derived_metrics(entry: Dict) -> Dict:
        """计算衍生财务指标"""
        metrics = {}
        rev = entry.get("operating_revenue") or entry.get("total_revenue")
        cost = entry.get("operating_cost")
        profit = entry.get("net_profit")
        equity = entry.get("total_equity")
        assets = entry.get("total_assets")
        liab = entry.get("total_liabilities")

        # 毛利率
        if rev and cost and rev != 0:
            metrics["gross_margin"] = round((rev - cost) / rev * 100, 4)
        # 净利率
        if rev and profit and rev != 0:
            metrics["net_margin"] = round(profit / rev * 100, 4)
        # ROE
        if equity and profit and equity != 0:
            metrics["roe"] = round(profit / equity * 100, 4)
        # ROA
        if assets and profit and assets != 0:
            metrics["roa"] = round(profit / assets * 100, 4)
        # 资产负债率
        if assets and liab and assets != 0:
            metrics["debt_ratio"] = round(liab / assets * 100, 4)
        return metrics

    # ======================== 估值指标 ========================

    def collect_valuations(self, stock_code: str) -> int:
        """采集估值历史数据（PE-TTM、PB、PS-TTM、市值等）"""
        logger.info(f"采集 {stock_code} 估值指标...")
        self._rate_limit()
        try:
            df = call_akshare("valuation_indicator", symbol=stock_code)
        except AkshareAPIError as e:
            logger.error(f"{stock_code} 估值采集失败: {e}")
            return 0

        if df is None or df.empty:
            return 0

        col_map = {
            "trade_date": "trade_date", "日期": "trade_date",
            "pe": "pe_ttm", "pe_ttm": "pe_ttm", "市盈率(TTM)": "pe_ttm",
            "pb": "pb", "市净率": "pb",
            "ps": "ps_ttm", "ps_ttm": "ps_ttm",
            "total_mv": "total_market_value", "总市值": "total_market_value",
            "circ_mv": "circulating_market_value", "流通市值": "circulating_market_value",
            "dv_ratio": "dividend_yield", "股息率": "dividend_yield",
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

        rows = []
        for _, row in df.iterrows():
            td = _safe_date(row.get("trade_date"))
            if td is None:
                continue
            rows.append({
                "stock_code": stock_code,
                "trade_date": td,
                "pe_ttm": _safe_float(row.get("pe_ttm")),
                "pb": _safe_float(row.get("pb")),
                "ps_ttm": _safe_float(row.get("ps_ttm")),
                "total_market_value": _safe_float(row.get("total_market_value")),
                "circulating_market_value": _safe_float(row.get("circulating_market_value")),
                "dividend_yield": _safe_float(row.get("dividend_yield")),
            })

        if rows:
            self._upsert(Valuation, rows, ["stock_code", "trade_date"])
        logger.info(f"{stock_code} 估值数据写入 {len(rows)} 条")
        return len(rows)

    # ======================== 分红数据 ========================

    def collect_dividends(self, stock_code: str) -> int:
        """采集历年分红方案"""
        logger.info(f"采集 {stock_code} 分红数据...")
        self._rate_limit()
        try:
            df = call_akshare("dividends", symbol=stock_code)
        except AkshareAPIError as e:
            logger.error(f"{stock_code} 分红数据采集失败: {e}")
            return 0

        if df is None or df.empty:
            return 0

        rows = []
        for _, row in df.iterrows():
            ex_date = _safe_date(
                self._find_col(row, ["除权除息日", "ex_dividend_date"])
            )
            rows.append({
                "stock_code": stock_code,
                "ex_dividend_date": ex_date,
                "cash_dividend": _safe_float(
                    self._find_col(row, ["每股派息(税前)", "每股分红", "cash_dividend"])
                ),
                "bonus_ratio": _safe_float(
                    self._find_col(row, ["送股(股)", "bonus_ratio"])
                ),
                "capital_increase": _safe_float(
                    self._find_col(row, ["转增(股)", "capital_increase"])
                ),
            })

        if rows:
            self._upsert(Dividend, rows, ["stock_code", "ex_dividend_date"])
        logger.info(f"{stock_code} 分红数据写入 {len(rows)} 条")
        return len(rows)

    # ======================== 行业板块 ========================

    def collect_industries(self) -> int:
        """采集行业板块列表和成分股"""
        logger.info("采集行业板块数据...")
        self._rate_limit()
        try:
            df = call_akshare("industry_list")
        except AkshareAPIError as e:
            logger.error(f"行业板块列表采集失败: {e}")
            return 0

        if df is None or df.empty:
            return 0

        industry_names = df.iloc[:, 0].dropna().tolist()
        industry_rows = [{"name": str(n).strip()} for n in industry_names if n]
        if industry_rows:
            self._upsert(Industry, industry_rows, ["name"])

        total_members = 0
        for name in industry_names[:50]:  # 限制采集数量避免超时
            self._rate_limit(1.0, 2.0)
            try:
                mdf = call_akshare("industry_constituents", symbol=str(name).strip())
                if mdf is None or mdf.empty:
                    continue
                member_rows = []
                for _, mrow in mdf.iterrows():
                    code = str(mrow.get("代码", mrow.get("stock_code", ""))).strip()
                    mname = str(mrow.get("名称", mrow.get("stock_name", ""))).strip()
                    if code:
                        member_rows.append({
                            "industry_name": str(name).strip(),
                            "stock_code": code,
                            "stock_name": mname,
                        })
                if member_rows:
                    self._upsert(IndustryMember, member_rows, ["industry_name", "stock_code"])
                    total_members += len(member_rows)
            except Exception as e:
                logger.warning(f"板块 {name} 成分股采集失败: {e}")

        logger.info(f"行业数据采集完成，{len(industry_names)} 个板块，{total_members} 条成分股")
        return total_members
