"""
核心数据采集模块

负责从 akshare 获取数据并写入三张核心表：
1. StockBasic - 股票基础信息
2. DailyMarketValuation - 日度量价与估值
3. QuarterlyFinance - 季度财务核心

参考 ZhuLinsen/daily_stock_analysis 的数据获取逻辑，
支持增量更新和全量更新两种模式。

所有接口调用通过 api_compat.call_akshare() 统一入口。
"""
import logging
import time
import random
from datetime import datetime, date, timedelta
from typing import List, Optional, Dict, Any

import pandas as pd
from sqlalchemy.orm import Session

from collectors.base import BaseCollector
from models.core import StockBasic, DailyMarketValuation, QuarterlyFinance
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
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, str):
        for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d"):
            try:
                return datetime.strptime(val.strip(), fmt).date()
            except ValueError:
                continue
    return None


def _infer_ts_code(code: str) -> str:
    """
    根据纯数字股票代码推断带后缀的 ts_code。

    000001 -> 000001.SZ
    600519 -> 600519.SH
    """
    code = str(code).strip().zfill(6)
    if code.startswith(("60", "68")):
        return f"{code}.SH"
    elif code.startswith(("00", "30")):
        return f"{code}.SZ"
    elif code.startswith(("43", "83", "87", "88")):
        return f"{code}.BJ"
    logger.warning(f"无法识别股票代码 {code} 的交易所前缀，默认归入 SZ")
    return f"{code}.SZ"


def _ts_code_to_pure(ts_code: str) -> str:
    """从 ts_code 中提取纯数字代码：000001.SZ -> 000001"""
    return ts_code.split(".")[0] if "." in ts_code else ts_code


class CoreCollector(BaseCollector):
    """
    核心数据采集器

    负责采集三张核心表的数据，支持增量和全量更新。
    """

    # ======================== 股票基础信息 ========================

    def collect_stock_basic(self) -> int:
        """
        采集全市场 A 股基础信息，写入 stock_basic 表。

        数据源: akshare stock_list
        更新策略: 全量 upsert
        """
        logger.info("开始采集 A 股基础信息到 stock_basic...")
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
                "ts_code": _infer_ts_code(code),
                "name": name,
                "industry": None,  # 行业信息后续由行业采集补充
                "is_delist": False,
            })

        if rows:
            self._upsert(StockBasic, rows, ["ts_code"])
            logger.info(f"stock_basic 写入/更新 {len(rows)} 条")
            return len(rows)
        logger.warning("stock_basic 采集结果为空")
        return 0

    # ======================== 日度量价与估值 ========================

    def collect_daily_market_valuation(
        self,
        ts_code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        force_full: bool = False,
    ) -> int:
        """
        采集日度量价与估值数据，写入 daily_market_valuation 表。

        数据采集策略（借鉴 daily_stock_analysis 的增量逻辑）：
        1. 增量模式：查询已有最新日期，只拉取之后的增量数据
        2. 全量模式：force_full=True 时忽略已有数据，全量拉取

        数据合并：
        - 日K线行情（close, 换手率 from stock_zh_a_hist）
        - 估值指标（pe_ttm, pb, ps_ttm, 市值, 股息率 from stock_a_indicator_lg）
        两者按 trade_date 合并写入同一条记录。

        :param ts_code: 带后缀的股票代码（如 000001.SZ）
        :param start_date: 开始日期 YYYYMMDD
        :param end_date: 结束日期 YYYYMMDD
        :param force_full: 是否强制全量采集
        :return: 写入行数
        """
        pure_code = _ts_code_to_pure(ts_code)

        if end_date is None:
            end_date = datetime.today().strftime("%Y%m%d")

        if start_date is None:
            cutoff = datetime.today() - timedelta(days=365 * HISTORY_YEARS_QUOTES)
            start_date = cutoff.strftime("%Y%m%d")

        # 增量模式：找到已有数据的最新日期
        if not force_full:
            from sqlalchemy import text
            latest = self.db.execute(
                text(
                    "SELECT MAX(trade_date) FROM daily_market_valuation "
                    "WHERE ts_code = :ts_code"
                ),
                {"ts_code": ts_code},
            ).scalar()
            if latest:
                if isinstance(latest, str):
                    latest = datetime.strptime(latest, "%Y-%m-%d").date()
                incremental_start = (latest + timedelta(days=1)).strftime("%Y%m%d")
                if incremental_start > end_date:
                    logger.debug(f"{ts_code} daily_market_valuation 已是最新，跳过")
                    return 0
                start_date = incremental_start

        # ---- 采集日K线行情 ----
        self._rate_limit(0.5, 1.0)
        quotes_data = {}
        try:
            df_quotes = call_akshare(
                "daily_quotes",
                symbol=pure_code,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust="",  # 不复权，原始价格
            )
            if df_quotes is not None and not df_quotes.empty:
                col_map = {
                    "日期": "trade_date", "date": "trade_date",
                    "收盘": "close", "close": "close",
                    "换手率": "turnover_rate", "turnover_rate": "turnover_rate",
                }
                df_quotes = df_quotes.rename(
                    columns={k: v for k, v in col_map.items() if k in df_quotes.columns}
                )
                for _, row in df_quotes.iterrows():
                    td = _safe_date(row.get("trade_date"))
                    if td is None:
                        continue
                    quotes_data[td] = {
                        "close": _safe_float(row.get("close")),
                        "turnover_rate": _safe_float(row.get("turnover_rate")),
                    }
        except AkshareAPIError as e:
            logger.warning(f"{ts_code} 日K线行情采集失败: {e}")

        # ---- 采集估值指标 ----
        self._rate_limit(0.5, 1.0)
        valuation_data = {}
        try:
            df_val = call_akshare("valuation_indicator", symbol=pure_code)
            if df_val is not None and not df_val.empty:
                col_map = {
                    "trade_date": "trade_date", "日期": "trade_date",
                    "pe": "pe_ttm", "pe_ttm": "pe_ttm", "市盈率(TTM)": "pe_ttm",
                    "pb": "pb", "市净率": "pb",
                    "ps": "ps_ttm", "ps_ttm": "ps_ttm",
                    "total_mv": "total_mv", "总市值": "total_mv",
                    "dv_ratio": "dv_ttm", "股息率": "dv_ttm",
                    "pcf": "pcf_ttm", "pcf_ocf": "pcf_ttm",
                }
                df_val = df_val.rename(
                    columns={k: v for k, v in col_map.items() if k in df_val.columns}
                )
                for _, row in df_val.iterrows():
                    td = _safe_date(row.get("trade_date"))
                    if td is None:
                        continue
                    valuation_data[td] = {
                        "pe_ttm": _safe_float(row.get("pe_ttm")),
                        "pb": _safe_float(row.get("pb")),
                        "ps_ttm": _safe_float(row.get("ps_ttm")),
                        "total_mv": _safe_float(row.get("total_mv")),
                        "dv_ttm": _safe_float(row.get("dv_ttm")),
                        "pcf_ttm": _safe_float(row.get("pcf_ttm")),
                    }
        except AkshareAPIError as e:
            logger.warning(f"{ts_code} 估值指标采集失败: {e}")

        # ---- 合并行情 + 估值数据 ----
        all_dates = set(quotes_data.keys()) | set(valuation_data.keys())
        # 过滤日期范围
        start_dt = datetime.strptime(start_date, "%Y%m%d").date()
        end_dt = datetime.strptime(end_date, "%Y%m%d").date()
        all_dates = {d for d in all_dates if start_dt <= d <= end_dt}

        rows = []
        for td in sorted(all_dates):
            q = quotes_data.get(td, {})
            v = valuation_data.get(td, {})
            rows.append({
                "ts_code": ts_code,
                "trade_date": td,
                "close": q.get("close"),
                "adj_factor": None,  # 复权因子需额外数据源或后续计算
                "turnover_rate": q.get("turnover_rate"),
                "total_mv": v.get("total_mv"),
                "pe_ttm": v.get("pe_ttm"),
                "pb": v.get("pb"),
                "dv_ttm": v.get("dv_ttm"),
                "ps_ttm": v.get("ps_ttm"),
                "pcf_ttm": v.get("pcf_ttm"),
            })

        if rows:
            self._upsert(DailyMarketValuation, rows, ["ts_code", "trade_date"])
        logger.debug(f"{ts_code} daily_market_valuation 写入 {len(rows)} 条")
        return len(rows)

    # ======================== 季度财务核心 ========================

    def collect_quarterly_finance(self, ts_code: str) -> int:
        """
        采集季度财务核心数据，写入 quarterly_finance 表。

        数据整合逻辑（借鉴 daily_stock_analysis 的 fundamental_adapter 模式）：
        1. 从利润表采集 total_revenue, net_profit, net_profit_deduct
        2. 从现金流量表采集 net_cash_flows_oper
        3. 从衍生指标计算或采集 roe, gross_margin, liability_to_asset

        :param ts_code: 带后缀的股票代码
        :return: 写入行数
        """
        logger.info(f"采集 {ts_code} 季度财务数据到 quarterly_finance...")
        pure_code = _ts_code_to_pure(ts_code)

        # 数据缓存 {end_date_str: {fields...}}
        data_map: Dict[str, Dict] = {}

        # ---- 采集利润表 ----
        self._rate_limit()
        try:
            df = call_akshare("financial_income", symbol=pure_code)
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    end_date_str = self._extract_report_date(row)
                    if not end_date_str:
                        continue
                    if end_date_str not in data_map:
                        data_map[end_date_str] = {}
                    entry = data_map[end_date_str]
                    entry["total_revenue"] = _safe_float(
                        self._pick_col(row, ["营业总收入", "total_revenue"])
                    )
                    entry["net_profit"] = _safe_float(
                        self._pick_col(row, ["净利润", "net_profit"])
                    )
                    entry["net_profit_deduct"] = _safe_float(
                        self._pick_col(row, [
                            "扣除非经常性损益后的净利润",
                            "net_profit_deducted", "net_profit_deduct",
                        ])
                    )
                    # 毛利率计算
                    rev = _safe_float(
                        self._pick_col(row, ["营业收入", "operating_revenue"])
                    ) or entry.get("total_revenue")
                    cost = _safe_float(
                        self._pick_col(row, ["营业总成本", "营业成本", "operating_cost"])
                    )
                    if rev and cost and rev != 0:
                        entry["gross_margin"] = round((rev - cost) / rev * 100, 4)
        except AkshareAPIError as e:
            logger.warning(f"{ts_code} 利润表采集失败: {e}")

        # ---- 采集资产负债表（用于资产负债率和ROE） ----
        self._rate_limit()
        try:
            df = call_akshare("financial_balance", symbol=pure_code)
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    end_date_str = self._extract_report_date(row)
                    if not end_date_str:
                        continue
                    if end_date_str not in data_map:
                        data_map[end_date_str] = {}
                    entry = data_map[end_date_str]
                    total_assets = _safe_float(
                        self._pick_col(row, ["资产总计", "total_assets"])
                    )
                    total_liab = _safe_float(
                        self._pick_col(row, ["负债合计", "total_liabilities"])
                    )
                    equity = _safe_float(
                        self._pick_col(row, [
                            "所有者权益合计",
                            "归属于母公司所有者权益合计",
                            "total_equity",
                        ])
                    )
                    # 资产负债率
                    if total_assets and total_liab and total_assets != 0:
                        entry["liability_to_asset"] = round(
                            total_liab / total_assets * 100, 4
                        )
                    # ROE
                    profit = entry.get("net_profit")
                    if profit and equity and equity != 0:
                        entry["roe"] = round(profit / equity * 100, 4)
        except AkshareAPIError as e:
            logger.warning(f"{ts_code} 资产负债表采集失败: {e}")

        # ---- 采集现金流量表 ----
        self._rate_limit()
        try:
            df = call_akshare("financial_cashflow", symbol=pure_code)
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    end_date_str = self._extract_report_date(row)
                    if not end_date_str:
                        continue
                    if end_date_str not in data_map:
                        data_map[end_date_str] = {}
                    entry = data_map[end_date_str]
                    entry["net_cash_flows_oper"] = _safe_float(
                        self._pick_col(row, [
                            "经营活动产生的现金流量净额",
                            "operating_cash_flow",
                        ])
                    )
        except AkshareAPIError as e:
            logger.warning(f"{ts_code} 现金流量表采集失败: {e}")

        # ---- 组装行并写入 ----
        rows = []
        for end_date_str, fields in data_map.items():
            ed = _safe_date(end_date_str)
            if ed is None:
                continue
            rows.append({
                "ts_code": ts_code,
                "end_date": ed,
                "ann_date": None,  # 公告日期需额外数据源
                "total_revenue": fields.get("total_revenue"),
                "net_profit": fields.get("net_profit"),
                "net_profit_deduct": fields.get("net_profit_deduct"),
                "net_cash_flows_oper": fields.get("net_cash_flows_oper"),
                "roe": fields.get("roe"),
                "gross_margin": fields.get("gross_margin"),
                "liability_to_asset": fields.get("liability_to_asset"),
            })

        if rows:
            self._upsert(QuarterlyFinance, rows, ["ts_code", "end_date"])
        logger.info(f"{ts_code} quarterly_finance 写入 {len(rows)} 期")
        return len(rows)

    # ======================== 工具方法 ========================

    @staticmethod
    def _extract_report_date(row) -> Optional[str]:
        """从行数据中提取报告期日期字符串"""
        for col_name in ["报告期", "report_date", "REPORT_DATE", "date"]:
            if col_name in row.index and pd.notna(row[col_name]):
                d = _safe_date(str(row[col_name]))
                if d:
                    return str(d)
        return None

    @staticmethod
    def _pick_col(row, candidates: List[str]):
        """在行数据中按候选列名查找值"""
        for c in candidates:
            if c in row.index and pd.notna(row[c]):
                return row[c]
        return None
