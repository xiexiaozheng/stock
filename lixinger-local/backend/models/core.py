"""
核心金融数据表 ORM 模型

本模块定义了三个核心数据表，参考 ZhuLinsen/daily_stock_analysis 的数据结构设计：
1. StockBasic - 股票基础信息表
2. DailyMarketValuation - 日度量价与估值表（联合主键优化大数据查询）
3. QuarterlyFinance - 季度财务核心表（联合主键 + 公告日期防前视偏差）

设计原则：
- 遵循 PEP8 规范
- 金额和比率字段使用 Float 类型：虽然 Float 存在浮点精度限制，
  但选择 Float 是为了与 pandas/numpy 生态无缝兼容（DataFrame 操作），
  在量化分析场景中精度完全满足要求（PE/PB/ROE 等指标通常仅保留 2-4 位小数）
- 每个字段添加详细中文注释说明含义
- 联合主键 + 联合索引优化查询性能
"""
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Column, String, Date, Boolean, Float, Index
from pydantic import BaseModel

from database import Base


# =====================================================================
# 表1：股票基础信息表 StockBasic
# =====================================================================

class StockBasic(Base):
    """
    股票基础信息表

    存储 A 股全市场股票的基础元数据，包括代码、名称、行业、上市日期和退市状态。
    主键为带后缀的股票代码（如 000001.SZ），与 Tushare 编码规范一致。
    """
    __tablename__ = "stock_basic"

    ts_code = Column(
        String(12),
        primary_key=True,
        comment="带后缀的股票代码，如 000001.SZ、600519.SH",
    )
    name = Column(
        String(50),
        nullable=False,
        comment="股票简称，如 平安银行、贵州茅台",
    )
    industry = Column(
        String(50),
        nullable=True,
        comment="所属行业，如 银行、白酒",
    )
    list_date = Column(
        Date,
        nullable=True,
        comment="上市日期",
    )
    is_delist = Column(
        Boolean,
        default=False,
        nullable=False,
        comment="是否已退市，True=已退市，False=正常上市",
    )

    def __repr__(self) -> str:
        return f"<StockBasic(ts_code={self.ts_code!r}, name={self.name!r})>"


# =====================================================================
# 表2：日度量价与估值表 DailyMarketValuation
# =====================================================================

class DailyMarketValuation(Base):
    """
    日度量价与估值表

    存储每只股票每个交易日的核心量价和估值数据。
    由于日线数据量极大（数千只股票 × 数千个交易日），
    在 __table_args__ 中显式设置 ts_code + trade_date 为联合主键，
    并建立联合索引以优化按股票代码和日期范围的查询性能。
    """
    __tablename__ = "daily_market_valuation"

    ts_code = Column(
        String(12),
        primary_key=True,
        nullable=False,
        comment="带后缀的股票代码，如 000001.SZ",
    )
    trade_date = Column(
        Date,
        primary_key=True,
        nullable=False,
        comment="交易日期",
    )

    # ------ 量价字段 ------
    close = Column(
        Float,
        nullable=True,
        comment="收盘价（元），未复权原始价格",
    )
    adj_factor = Column(
        Float,
        nullable=True,
        comment="后复权因子，复权价 = close × adj_factor。注意：当前未自动填充，需额外数据源或后续计算",
    )
    turnover_rate = Column(
        Float,
        nullable=True,
        comment="换手率（%），成交量占流通股本的百分比",
    )

    # ------ 市值字段 ------
    total_mv = Column(
        Float,
        nullable=True,
        comment="总市值（万元），= 总股本 × 收盘价",
    )

    # ------ 估值字段 ------
    pe_ttm = Column(
        Float,
        nullable=True,
        comment="滚动市盈率（TTM），= 总市值 / 最近12个月归母净利润",
    )
    pb = Column(
        Float,
        nullable=True,
        comment="市净率，= 总市值 / 最新报告期归属母公司股东的净资产",
    )
    dv_ttm = Column(
        Float,
        nullable=True,
        comment="近12个月股息率（%），= 最近12个月现金分红 / 总市值 × 100",
    )
    ps_ttm = Column(
        Float,
        nullable=True,
        comment="滚动市销率（TTM），= 总市值 / 最近12个月营业收入",
    )
    pcf_ttm = Column(
        Float,
        nullable=True,
        comment="滚动市现率（TTM），= 总市值 / 最近12个月经营活动现金流净额",
    )

    __table_args__ = (
        Index("ix_dmv_ts_code_trade_date", "ts_code", "trade_date"),
        {"comment": "日度量价与估值数据，联合主键为 ts_code + trade_date"},
    )

    def __repr__(self) -> str:
        return (
            f"<DailyMarketValuation("
            f"ts_code={self.ts_code!r}, trade_date={self.trade_date!r}, "
            f"close={self.close}, pe_ttm={self.pe_ttm})>"
        )


# =====================================================================
# 表3：季度财务核心表 QuarterlyFinance
# =====================================================================

class QuarterlyFinance(Base):
    """
    季度财务核心表

    存储每只股票每个报告期的核心财务数据（利润表、现金流、关键比率）。
    同样在 __table_args__ 中显式设置 ts_code + end_date 为联合主键，
    并建立联合索引以优化查询。

    包含 ann_date（实际公告日期）字段，可用于回测时防范前视偏差（look-ahead bias）。
    """
    __tablename__ = "quarterly_finance"

    ts_code = Column(
        String(12),
        primary_key=True,
        nullable=False,
        comment="带后缀的股票代码，如 000001.SZ",
    )
    end_date = Column(
        Date,
        primary_key=True,
        nullable=False,
        comment="报告期截止日期，如 2024-12-31（年报）、2024-09-30（三季报）",
    )

    # ------ 防前视偏差 ------
    ann_date = Column(
        Date,
        nullable=True,
        comment="实际公告日期，用于回测时防范前视偏差。注意：当前未自动填充，回测时需确认数据可用性",
    )

    # ------ 利润表核心 ------
    total_revenue = Column(
        Float,
        nullable=True,
        comment="营业总收入（元），反映企业总体经营规模",
    )
    net_profit = Column(
        Float,
        nullable=True,
        comment="归属母公司股东的净利润（元），最核心的盈利指标",
    )
    net_profit_deduct = Column(
        Float,
        nullable=True,
        comment="扣除非经常性损益后的净利润（元），剔除一次性损益更能反映主业盈利",
    )

    # ------ 现金流核心 ------
    net_cash_flows_oper = Column(
        Float,
        nullable=True,
        comment="经营活动产生的现金流量净额（元），反映企业造血能力",
    )

    # ------ 财务比率 ------
    roe = Column(
        Float,
        nullable=True,
        comment="净资产收益率（%），= 归母净利润 / 归母净资产 × 100",
    )
    gross_margin = Column(
        Float,
        nullable=True,
        comment="毛利率（%），= (营业收入 - 营业成本) / 营业收入 × 100",
    )
    liability_to_asset = Column(
        Float,
        nullable=True,
        comment="资产负债率（%），= 总负债 / 总资产 × 100，反映企业杠杆水平",
    )

    __table_args__ = (
        Index("ix_qf_ts_code_end_date", "ts_code", "end_date"),
        {"comment": "季度财务核心数据，联合主键为 ts_code + end_date"},
    )

    def __repr__(self) -> str:
        return (
            f"<QuarterlyFinance("
            f"ts_code={self.ts_code!r}, end_date={self.end_date!r}, "
            f"net_profit={self.net_profit}, roe={self.roe})>"
        )


# =====================================================================
# Pydantic Response Schemas
# =====================================================================

class StockBasicResponse(BaseModel):
    """股票基础信息响应模型"""
    ts_code: str
    name: str
    industry: Optional[str] = None
    list_date: Optional[date] = None
    is_delist: bool = False

    class Config:
        from_attributes = True


class StockBasicListResponse(BaseModel):
    """股票基础信息列表响应"""
    total: int
    page: int
    page_size: int
    items: list[StockBasicResponse]


class DailyMarketValuationResponse(BaseModel):
    """日度量价与估值响应模型"""
    ts_code: str
    trade_date: date
    close: Optional[float] = None
    adj_factor: Optional[float] = None
    turnover_rate: Optional[float] = None
    total_mv: Optional[float] = None
    pe_ttm: Optional[float] = None
    pb: Optional[float] = None
    dv_ttm: Optional[float] = None
    ps_ttm: Optional[float] = None
    pcf_ttm: Optional[float] = None

    class Config:
        from_attributes = True


class QuarterlyFinanceResponse(BaseModel):
    """季度财务核心响应模型"""
    ts_code: str
    end_date: date
    ann_date: Optional[date] = None
    total_revenue: Optional[float] = None
    net_profit: Optional[float] = None
    net_profit_deduct: Optional[float] = None
    net_cash_flows_oper: Optional[float] = None
    roe: Optional[float] = None
    gross_margin: Optional[float] = None
    liability_to_asset: Optional[float] = None

    class Config:
        from_attributes = True
