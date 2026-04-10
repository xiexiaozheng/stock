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
from data_provider.base import DataFetcherManager, DataFetchError
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
    """安全转换为 date 对象，兼容多种格式（含带时间的字符串和中文日期）"""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    if isinstance(val, str):
        s = val.strip()
        # Strip time portion if present: "2024-12-31 00:00:00" or "2024-12-31T00:00:00"
        if len(s) > 10 and s[10] in (" ", "T"):
            s = s[:10]
        for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d", "%Y年%m月%d日"):
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                continue
    return None


def _to_dash_date_text(val: Any) -> str:
    parsed = _safe_date(val)
    if parsed is None:
        raise ValueError(f"invalid date value: {val}")
    return parsed.strftime("%Y-%m-%d")


def _infer_exchange(code: str) -> str:
    """根据股票代码推断交易所"""
    if code.startswith(("60", "68")):
        return "SH"
    elif code.startswith(("00", "30")):
        return "SZ"
    elif code.startswith(("43", "83", "87", "88", "92")):
        return "BJ"
    return "SZ"


class AkshareCollector(BaseCollector):
    """akshare 数据采集器"""

    def __init__(self, db: Session, manager: Optional[DataFetcherManager] = None):
        super().__init__(db)
        self._manager = manager
        self._owns_manager = manager is None

    @property
    def manager(self) -> DataFetcherManager:
        if self._manager is None:
            self._manager = DataFetcherManager()
        return self._manager

    def close(self) -> None:
        if self._owns_manager and self._manager is not None:
            self._manager.close()
            self._manager = None

    # ======================== 股票列表 ========================

    def collect_stock_list(self) -> int:
        """采集全市场 A 股列表，写入 stocks 表"""
        logger.info("开始采集 A 股股票列表...")
        df = self.manager.get_stock_list()
        if df is None or df.empty:
            logger.error(
                "股票列表采集失败: %s",
                self.manager.get_last_request_diagnostic("stock_list"),
            )
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
            df, source = self.manager.get_daily_data(
                stock_code,
                start_date=_to_dash_date_text(start_date),
                end_date=_to_dash_date_text(end_date),
                days=0,
            )
            logger.info(
                "%s 日线来自 %s, 诊断=%s",
                stock_code,
                source,
                self.manager.get_last_request_diagnostic("daily_quotes"),
            )
        except DataFetchError as e:
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
        data_map: Dict[date, Dict] = {}
        frames = self.manager.get_financial_report_frames(stock_code)

        income_df = frames.get("income")
        if income_df is not None and not income_df.empty:
            _skipped: list = []
            for _, row in income_df.iterrows():
                key, rt, raw_val = self._parse_report_key(row)
                if key is None:
                    _skipped.append(raw_val)
                    continue
                if key not in data_map:
                    data_map[key] = {"report_type": rt}
                entry = data_map[key]
                entry["total_revenue"] = _safe_float(self._find_col(row, ["营业总收入", "total_revenue"]))
                entry["operating_revenue"] = _safe_float(self._find_col(row, ["营业收入", "operating_revenue"]))
                entry["operating_cost"] = _safe_float(self._find_col(row, ["营业总成本", "营业成本", "operating_cost"]))
                rev = entry.get("operating_revenue") or entry.get("total_revenue")
                cost = entry.get("operating_cost")
                entry["gross_profit"] = (rev - cost) if (rev is not None and cost is not None) else None
                entry["net_profit"] = _safe_float(self._find_col(row, ["净利润", "net_profit"]))
                entry["net_profit_deducted"] = _safe_float(
                    self._find_col(row, ["扣除非经常性损益后的净利润", "net_profit_deducted"])
                )
            if _skipped:
                logger.warning(
                    "%s 利润表存在 %d 个无法解析的报告期，已跳过 (首例: %r)",
                    stock_code, len(_skipped), _skipped[0],
                )

        balance_df = frames.get("balance")
        if balance_df is not None and not balance_df.empty:
            _skipped = []
            for _, row in balance_df.iterrows():
                key, rt, raw_val = self._parse_report_key(row)
                if key is None:
                    _skipped.append(raw_val)
                    continue
                if key not in data_map:
                    data_map[key] = {"report_type": rt}
                entry = data_map[key]
                entry["total_assets"] = _safe_float(self._find_col(row, ["资产总计", "total_assets"]))
                entry["total_liabilities"] = _safe_float(self._find_col(row, ["负债合计", "total_liabilities"]))
                entry["total_equity"] = _safe_float(self._find_col(row, ["所有者权益合计", "归属于母公司所有者权益合计", "total_equity"]))
                entry["goodwill"] = _safe_float(self._find_col(row, ["商誉", "goodwill"]))
            if _skipped:
                logger.warning(
                    "%s 资产负债表存在 %d 个无法解析的报告期，已跳过 (首例: %r)",
                    stock_code, len(_skipped), _skipped[0],
                )

        cashflow_df = frames.get("cashflow")
        if cashflow_df is not None and not cashflow_df.empty:
            _skipped = []
            for _, row in cashflow_df.iterrows():
                key, rt, raw_val = self._parse_report_key(row)
                if key is None:
                    _skipped.append(raw_val)
                    continue
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
                entry["free_cash_flow"] = ocf + icf if (ocf is not None and icf is not None) else None
            if _skipped:
                logger.warning(
                    "%s 现金流量表存在 %d 个无法解析的报告期，已跳过 (首例: %r)",
                    stock_code, len(_skipped), _skipped[0],
                )

        rows = []
        for report_date, fields in data_map.items():
            # 计算衍生指标
            row = dict(fields)
            row.update(self._calc_derived_metrics(row))
            row["stock_code"] = stock_code
            normalized_report_date = _safe_date(report_date)
            if normalized_report_date is None:
                logger.warning("%s 财务报表存在无效 report_date，已跳过: %s", stock_code, report_date)
                continue
            row["report_date"] = normalized_report_date
            rows.append(row)

        if rows:
            self._upsert(Financial, rows, ["stock_code", "report_type", "report_date"])
        logger.info(f"{stock_code} 财务报表写入 {len(rows)} 期")
        return len(rows)

    def _collect_income(self, stock_code: str, data_map: Dict):
        """采集利润表"""
        self._rate_limit()
        try:
            df = call_akshare("financial_income", stock=stock_code)
        except AkshareAPIError as e:
            logger.warning(f"{stock_code} 利润表采集失败: {e}")
            return

        if df is None or df.empty:
            return

        for _, row in df.iterrows():
            key, rt, _raw = self._parse_report_key(row)
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
            df = call_akshare("financial_balance", stock=stock_code)
        except AkshareAPIError as e:
            logger.warning(f"{stock_code} 资产负债表采集失败: {e}")
            return

        if df is None or df.empty:
            return

        for _, row in df.iterrows():
            key, rt, _raw = self._parse_report_key(row)
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
            df = call_akshare("financial_cashflow", stock=stock_code)
        except AkshareAPIError as e:
            logger.warning(f"{stock_code} 现金流量表采集失败: {e}")
            return

        if df is None or df.empty:
            return

        for _, row in df.iterrows():
            key, rt, _raw = self._parse_report_key(row)
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
        """从行数据中解析报告期 key 和 report_type，返回 (date|None, report_type, raw_val)"""
        date_col = self._find_col(row, ["报告期", "report_date", "REPORT_DATE", "date"])
        if date_col is not None:
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
                return d, rt, str(date_col)
        return None, "annual", str(date_col) if date_col is not None else None

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
        """
        采集估值历史数据（PE-TTM、PB、PS-TTM、市值等）。

        注意：历史估值序列依赖的 AKShare 接口 stock_a_indicator_lg 在当前版本中不可用，
        该能力已标记为禁用。此方法将立即返回 0，不写入任何数据。
        最新估值快照请通过 CoreCollector.collect_latest_valuation_snapshot() 获取。
        """
        logger.debug(
            "%s 历史估值数据源不可用: stock_a_indicator_lg 在当前 AKShare 版本中不存在，"
            "跳过历史估值采集",
            stock_code,
        )
        return 0

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
