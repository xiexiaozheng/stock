"""
核心数据采集模块 — 多数据源版

负责从多个数据源获取数据并写入三张核心表：
1. StockBasic - 股票基础信息
2. DailyMarketValuation - 日度量价与估值
3. QuarterlyFinance - 季度财务核心

参考 ZhuLinsen/daily_stock_analysis 的多信源数据获取架构：
- 日K线行情: 通过 DataFetcherManager 自动 failover (efinance → akshare → tushare → baostock)
- 估值指标: 通过 api_compat.call_akshare() 兼容层
- 后复权因子: 通过 BaostockFetcher 专有接口
- 财务数据: 通过 api_compat.call_akshare() + FundamentalAdapter 补充

所有数据源接口都有独立的防封禁策略 (限流、熔断器、UA轮换、重试)。
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

# 多数据源框架
from data_provider.base import DataFetcherManager, DataFetchError, normalize_stock_code
from data_provider.realtime_types import safe_float as dp_safe_float

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
    核心数据采集器 — 多数据源版

    负责采集三张核心表的数据，支持增量和全量更新。
    日K线行情通过 DataFetcherManager 多数据源自动 failover 获取。
    估值、财务数据通过 api_compat + FundamentalAdapter 多接口探测获取。
    """

    def __init__(self, db: Session, manager: Optional[DataFetcherManager] = None):
        super().__init__(db)
        # 注入或自动创建 DataFetcherManager
        self._manager = manager
        self._owns_manager = False  # 是否由本类创建（需在 close 时释放）

    @property
    def manager(self) -> DataFetcherManager:
        """延迟初始化 DataFetcherManager"""
        if self._manager is None:
            self._manager = DataFetcherManager()
            self._owns_manager = True
            logger.info(
                f"CoreCollector 自动创建 DataFetcherManager, "
                f"已注册 {len(self._manager.get_fetchers())} 个数据源"
            )
        return self._manager

    def close(self):
        """释放资源"""
        if self._owns_manager and self._manager is not None:
            self._manager.close()
            self._manager = None

    # ======================== 股票基础信息 ========================

    def collect_stock_basic(self) -> int:
        """
        采集全市场 A 股基础信息，写入 stock_basic 表。

        多数据源策略:
        1. 优先通过 DataFetcherManager 获取 (efinance/akshare/tushare/baostock)
        2. 失败则 fallback 到 api_compat.call_akshare()

        更新策略: 全量 upsert
        """
        logger.info("开始采集 A 股基础信息到 stock_basic (多数据源)...")

        df = None
        source = "unknown"

        # 策略1: 通过 DataFetcherManager 获取股票列表
        try:
            df = self.manager.get_stock_list()
            if df is not None and not df.empty:
                source = "DataFetcherManager"
                logger.info(f"股票列表来自 DataFetcherManager, {len(df)} 条")
        except Exception as e:
            logger.warning(f"DataFetcherManager 股票列表失败: {e}")

        # 策略2: 通过 api_compat fallback
        if df is None or df.empty:
            try:
                df = call_akshare("stock_list")
                source = "api_compat"
                logger.info(f"股票列表来自 api_compat, {len(df)} 条")
            except AkshareAPIError as e:
                logger.error(f"股票列表采集全部失败: {e}")
                return 0

        if df is None or df.empty:
            logger.warning("stock_basic 采集结果为空")
            return 0

        rows = []
        for _, row in df.iterrows():
            code = str(
                row.get("code", row.get("股票代码", row.get("symbol", "")))
            ).strip().zfill(6)
            name = str(
                row.get("name", row.get("股票名称", row.get("stock_name", "")))
            ).strip()
            if not code or not name:
                continue
            rows.append({
                "ts_code": _infer_ts_code(code),
                "name": name,
                "industry": str(row.get("industry", "")) or None,
                "is_delist": False,
            })

        if rows:
            self._upsert(StockBasic, rows, ["ts_code"])
            logger.info(f"stock_basic 写入/更新 {len(rows)} 条 (来源: {source})")
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

        多数据源策略（参考 daily_stock_analysis 架构）:
        1. 日K线行情: DataFetcherManager 自动 failover
           (efinance → akshare → tushare → baostock)
        2. 估值指标: api_compat (stock_a_indicator_lg)
        3. 后复权因子: BaostockFetcher.get_adjust_factor() (独有)

        数据合并:
        - 日K线行情 (close, volume, turnover_rate from 多数据源)
        - 估值指标 (pe_ttm, pb, ps_ttm, 市值, 股息率 from akshare)
        - 后复权因子 (adj_factor from baostock)
        三者按 trade_date 合并写入同一条记录。

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

        # 转换日期格式 YYYYMMDD → YYYY-MM-DD (DataFetcherManager 使用)
        start_dash = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
        end_dash = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"

        # ---- 数据源1: 日K线行情（多数据源 failover）----
        quotes_data = {}
        data_source = "none"
        try:
            df_quotes, data_source = self.manager.get_daily_data(
                pure_code,
                start_date=start_dash,
                end_date=end_dash,
                days=0,  # 不限天数，用日期范围控制
            )
            if df_quotes is not None and not df_quotes.empty:
                logger.info(
                    f"{ts_code} 日K线来自 {data_source}, {len(df_quotes)} 行"
                )
                for _, row in df_quotes.iterrows():
                    td = _safe_date(row.get("date"))
                    if td is None:
                        continue
                    quotes_data[td] = {
                        "close": _safe_float(row.get("close")),
                        "turnover_rate": _safe_float(row.get("turnover_rate")),
                    }
        except DataFetchError as e:
            logger.warning(f"{ts_code} 日K线多数据源全部失败: {e}")
            # Fallback: 直接调用 api_compat (最后的保险)
            self._rate_limit(0.5, 1.0)
            try:
                df_quotes = call_akshare(
                    "daily_quotes",
                    symbol=pure_code,
                    period="daily",
                    start_date=start_date,
                    end_date=end_date,
                    adjust="",
                )
                if df_quotes is not None and not df_quotes.empty:
                    data_source = "api_compat_fallback"
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
            except AkshareAPIError as e2:
                logger.warning(f"{ts_code} api_compat fallback 也失败: {e2}")

        # ---- 数据源2: 估值指标 (akshare stock_a_indicator_lg) ----
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

        # ---- 数据源3: 后复权因子 (BaostockFetcher 独有) ----
        adj_factor_data = {}
        try:
            from data_provider.baostock_fetcher import BaostockFetcher
            bs_fetcher = None
            # 从 manager 中找已注册的 BaostockFetcher
            for f in self.manager.get_fetchers():
                if isinstance(f, BaostockFetcher):
                    bs_fetcher = f
                    break
            if bs_fetcher is None:
                bs_fetcher = BaostockFetcher()

            adj_df = bs_fetcher.get_adjust_factor(
                pure_code,
                start_date=start_dash,
                end_date=end_dash,
            )
            if adj_df is not None and not adj_df.empty:
                logger.info(f"{ts_code} 后复权因子来自 BaostockFetcher, {len(adj_df)} 行")
                for _, row in adj_df.iterrows():
                    td = _safe_date(row.get("dividOperateDate", row.get("date")))
                    if td is None:
                        continue
                    adj_factor_data[td] = _safe_float(
                        row.get("backAdjustFactor", row.get("foreAdjustFactor"))
                    )
        except Exception as e:
            logger.debug(f"{ts_code} 后复权因子获取失败 (非必须): {e}")

        # ---- 合并: 行情 + 估值 + 复权因子 ----
        all_dates = set(quotes_data.keys()) | set(valuation_data.keys())
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
                "adj_factor": adj_factor_data.get(td),  # 从 baostock 填充
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
        logger.debug(
            f"{ts_code} daily_market_valuation 写入 {len(rows)} 条 "
            f"(行情: {data_source}, 估值: akshare, "
            f"复权: {'baostock' if adj_factor_data else 'N/A'})"
        )
        return len(rows)

    # ======================== 季度财务核心 ========================

    def collect_quarterly_finance(self, ts_code: str) -> int:
        """
        采集季度财务核心数据，写入 quarterly_finance 表。

        多数据源策略（参考 daily_stock_analysis fundamental_adapter 模式）:
        1. 主数据源: api_compat 获取利润表/资产负债表/现金流量表
        2. 补充源: FundamentalAdapter fail-open 模式补充增长/盈利指标
        3. 将 ROE、毛利率、资产负债率等衍生指标直接计算或从多源合并

        :param ts_code: 带后缀的股票代码
        :return: 写入行数
        """
        logger.info(f"采集 {ts_code} 季度财务数据到 quarterly_finance (多数据源)...")
        pure_code = _ts_code_to_pure(ts_code)

        # 数据缓存 {end_date_str: {fields...}}
        data_map: Dict[str, Dict] = {}

        # ---- 主数据源1: 利润表 ----
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

        # ---- 主数据源2: 资产负债表（用于资产负债率和ROE）----
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

        # ---- 主数据源3: 现金流量表 ----
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

        # ---- 补充数据源: FundamentalAdapter (fail-open) ----
        try:
            from data_provider.fundamental_adapter import FundamentalAdapter
            adapter = FundamentalAdapter()
            bundle = adapter.get_fundamental_bundle(pure_code, budget_seconds=5.0)
            if bundle.get("status") in ("ok", "partial"):
                # 将 FundamentalAdapter 的数据补充到最新报告期
                # 找最新的 end_date
                if data_map:
                    latest_end = max(data_map.keys())
                    entry = data_map[latest_end]

                    # 补充 ROE (如果主数据源未计算出)
                    earnings = bundle.get("earnings", {})
                    if entry.get("roe") is None and earnings.get("return_on_equity"):
                        entry["roe"] = _safe_float(earnings["return_on_equity"])
                        logger.debug(
                            f"{ts_code} ROE 由 FundamentalAdapter 补充: "
                            f"{entry['roe']}"
                        )

                logger.info(
                    f"{ts_code} FundamentalAdapter 补充状态: {bundle['status']}, "
                    f"来源链: {[s['provider'] for s in bundle.get('source_chain', [])]}"
                )
        except Exception as e:
            logger.debug(f"{ts_code} FundamentalAdapter 补充数据失败 (非必须): {e}")

        # ---- 组装行并写入 ----
        rows = []
        for end_date_str, fields in data_map.items():
            ed = _safe_date(end_date_str)
            if ed is None:
                continue
            rows.append({
                "ts_code": ts_code,
                "end_date": ed,
                "ann_date": None,  # 公告日期需 Tushare Token
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
