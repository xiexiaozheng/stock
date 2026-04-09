"""
数据读取接口层（Data Reader）

提供标准化的方法，从数据库中高效读取所需时间序列的 DataFrame。
所有指标计算和分析模块都应通过此接口获取数据，而非直接查询数据库。

设计原则：
- 统一的数据访问入口，隔离 ORM 细节
- 返回 pandas DataFrame，方便后续分析计算
- 支持灵活的时间范围和字段筛选
- 高效的批量查询（利用联合索引）
"""
import logging
from datetime import date, datetime, timedelta
from typing import Optional, List

import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import text

from utils.logger import get_logger

logger = get_logger(__name__)


class DataReader:
    """
    标准化数据读取接口

    所有数据访问都通过此类完成，为指标计算和分析提供一致的 DataFrame 输入。

    使用示例::

        reader = DataReader(db_session)

        # 读取单只股票的日度量价与估值数据
        df = reader.read_daily_market("000001.SZ", start_date="2020-01-01")

        # 读取财务数据
        df = reader.read_quarterly_finance("600519.SH", fields=["roe", "net_profit"])

        # 读取多只股票基础信息
        df = reader.read_stock_basic(ts_codes=["000001.SZ", "600519.SH"])
    """

    def __init__(self, db: Session):
        self.db = db

    # ======================== 股票基础信息 ========================

    def read_stock_basic(
        self,
        ts_codes: Optional[List[str]] = None,
        industry: Optional[str] = None,
        include_delisted: bool = False,
    ) -> pd.DataFrame:
        """
        读取股票基础信息。

        :param ts_codes: 可选的股票代码列表筛选
        :param industry: 可选的行业筛选
        :param include_delisted: 是否包含已退市股票，默认 False
        :return: DataFrame，列包含 ts_code, name, industry, list_date, is_delist
        """
        conditions = []
        params = {}

        if not include_delisted:
            conditions.append("is_delist = 0")

        if ts_codes:
            placeholders = ", ".join(f":code_{i}" for i in range(len(ts_codes)))
            conditions.append(f"ts_code IN ({placeholders})")
            for i, code in enumerate(ts_codes):
                params[f"code_{i}"] = code

        if industry:
            conditions.append("industry LIKE :industry")
            params["industry"] = f"%{industry}%"

        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        sql = f"SELECT ts_code, name, industry, list_date, is_delist FROM stock_basic {where}"

        try:
            df = pd.read_sql(text(sql), self.db.bind, params=params)
            return df
        except Exception as e:
            logger.error(f"读取 stock_basic 失败: {e}")
            return pd.DataFrame()

    # ======================== 日度量价与估值数据 ========================

    def read_daily_market(
        self,
        ts_code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        fields: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """
        读取单只股票的日度量价与估值时间序列数据。

        :param ts_code: 股票代码（含后缀，如 000001.SZ）
        :param start_date: 起始日期 YYYY-MM-DD，默认无限制
        :param end_date: 结束日期 YYYY-MM-DD，默认到最新
        :param fields: 需要的字段列表，默认全部字段
        :return: DataFrame，按 trade_date 升序排列
        """
        all_fields = [
            "ts_code", "trade_date", "close", "adj_factor",
            "turnover_rate", "total_mv", "pe_ttm", "pb",
            "dv_ttm", "ps_ttm", "pcf_ttm",
        ]
        if fields:
            select_fields = ["ts_code", "trade_date"] + [
                f for f in fields if f in all_fields and f not in ("ts_code", "trade_date")
            ]
        else:
            select_fields = all_fields

        conditions = ["ts_code = :ts_code"]
        params = {"ts_code": ts_code}

        if start_date:
            conditions.append("trade_date >= :start_date")
            params["start_date"] = start_date
        if end_date:
            conditions.append("trade_date <= :end_date")
            params["end_date"] = end_date

        where = " AND ".join(conditions)
        sql = (
            f"SELECT {', '.join(select_fields)} FROM daily_market_valuation "
            f"WHERE {where} ORDER BY trade_date ASC"
        )

        try:
            df = pd.read_sql(text(sql), self.db.bind, params=params)
            if "trade_date" in df.columns:
                df["trade_date"] = pd.to_datetime(df["trade_date"])
            return df
        except Exception as e:
            logger.error(f"读取 daily_market_valuation 失败 [{ts_code}]: {e}")
            return pd.DataFrame()

    def read_daily_market_batch(
        self,
        ts_codes: List[str],
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        fields: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """
        批量读取多只股票的日度量价与估值数据。

        :param ts_codes: 股票代码列表
        :param start_date: 起始日期
        :param end_date: 结束日期
        :param fields: 需要的字段列表
        :return: DataFrame，包含所有请求股票的数据
        """
        if not ts_codes:
            return pd.DataFrame()

        all_fields = [
            "ts_code", "trade_date", "close", "adj_factor",
            "turnover_rate", "total_mv", "pe_ttm", "pb",
            "dv_ttm", "ps_ttm", "pcf_ttm",
        ]
        if fields:
            select_fields = ["ts_code", "trade_date"] + [
                f for f in fields if f in all_fields and f not in ("ts_code", "trade_date")
            ]
        else:
            select_fields = all_fields

        placeholders = ", ".join(f":code_{i}" for i in range(len(ts_codes)))
        conditions = [f"ts_code IN ({placeholders})"]
        params = {f"code_{i}": code for i, code in enumerate(ts_codes)}

        if start_date:
            conditions.append("trade_date >= :start_date")
            params["start_date"] = start_date
        if end_date:
            conditions.append("trade_date <= :end_date")
            params["end_date"] = end_date

        where = " AND ".join(conditions)
        sql = (
            f"SELECT {', '.join(select_fields)} FROM daily_market_valuation "
            f"WHERE {where} ORDER BY ts_code, trade_date ASC"
        )

        try:
            df = pd.read_sql(text(sql), self.db.bind, params=params)
            if "trade_date" in df.columns:
                df["trade_date"] = pd.to_datetime(df["trade_date"])
            return df
        except Exception as e:
            logger.error(f"批量读取 daily_market_valuation 失败: {e}")
            return pd.DataFrame()

    # ======================== 季度财务数据 ========================

    def read_quarterly_finance(
        self,
        ts_code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        fields: Optional[List[str]] = None,
        annual_only: bool = False,
    ) -> pd.DataFrame:
        """
        读取单只股票的季度财务数据。

        :param ts_code: 股票代码
        :param start_date: 报告期起始日期
        :param end_date: 报告期结束日期
        :param fields: 需要的字段列表
        :param annual_only: 是否仅返回年报（end_date 月份为 12）
        :return: DataFrame，按 end_date 升序排列
        """
        all_fields = [
            "ts_code", "end_date", "ann_date",
            "total_revenue", "net_profit", "net_profit_deduct",
            "net_cash_flows_oper", "roe", "gross_margin", "liability_to_asset",
        ]
        if fields:
            select_fields = ["ts_code", "end_date"] + [
                f for f in fields if f in all_fields and f not in ("ts_code", "end_date")
            ]
        else:
            select_fields = all_fields

        conditions = ["ts_code = :ts_code"]
        params = {"ts_code": ts_code}

        if start_date:
            conditions.append("end_date >= :start_date")
            params["start_date"] = start_date
        if end_date:
            conditions.append("end_date <= :end_date")
            params["end_date"] = end_date
        if annual_only:
            # SQLite: strftime('%m', end_date) = '12'
            conditions.append("strftime('%m', end_date) = '12'")

        where = " AND ".join(conditions)
        sql = (
            f"SELECT {', '.join(select_fields)} FROM quarterly_finance "
            f"WHERE {where} ORDER BY end_date ASC"
        )

        try:
            df = pd.read_sql(text(sql), self.db.bind, params=params)
            if "end_date" in df.columns:
                df["end_date"] = pd.to_datetime(df["end_date"])
            if "ann_date" in df.columns:
                df["ann_date"] = pd.to_datetime(df["ann_date"])
            return df
        except Exception as e:
            logger.error(f"读取 quarterly_finance 失败 [{ts_code}]: {e}")
            return pd.DataFrame()

    # ======================== 便捷方法 ========================

    def get_latest_trade_date(self, ts_code: str) -> Optional[date]:
        """获取某只股票在 daily_market_valuation 中的最新交易日期"""
        sql = text(
            "SELECT MAX(trade_date) FROM daily_market_valuation WHERE ts_code = :ts_code"
        )
        result = self.db.execute(sql, {"ts_code": ts_code}).scalar()
        if result is None:
            return None
        if isinstance(result, str):
            return datetime.strptime(result, "%Y-%m-%d").date()
        return result

    def get_latest_report_date(self, ts_code: str) -> Optional[date]:
        """获取某只股票在 quarterly_finance 中的最新报告期"""
        sql = text(
            "SELECT MAX(end_date) FROM quarterly_finance WHERE ts_code = :ts_code"
        )
        result = self.db.execute(sql, {"ts_code": ts_code}).scalar()
        if result is None:
            return None
        if isinstance(result, str):
            return datetime.strptime(result, "%Y-%m-%d").date()
        return result

    def get_all_active_codes(self) -> List[str]:
        """获取所有未退市股票的代码列表"""
        sql = text("SELECT ts_code FROM stock_basic WHERE is_delist = 0")
        rows = self.db.execute(sql).fetchall()
        return [row[0] for row in rows]
