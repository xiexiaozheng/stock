"""财务报表数据模型"""
from datetime import datetime, date
from typing import Optional
from sqlalchemy import Column, Integer, String, Date, DateTime, Numeric, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from pydantic import BaseModel

from database import Base


class Financial(Base):
    __tablename__ = "financials"

    id = Column(Integer, primary_key=True, autoincrement=True)
    stock_code = Column(String(10), ForeignKey("stocks.stock_code"), nullable=False)
    report_type = Column(String(10), nullable=False)  # annual / Q1 / Q2 / Q3
    report_date = Column(Date, nullable=False)

    # 利润表核心字段
    total_revenue = Column(Numeric(20, 2))
    operating_revenue = Column(Numeric(20, 2))
    operating_cost = Column(Numeric(20, 2))
    gross_profit = Column(Numeric(20, 2))
    net_profit = Column(Numeric(20, 2))
    net_profit_deducted = Column(Numeric(20, 2))  # 扣非净利润

    # 资产负债表核心字段
    total_assets = Column(Numeric(20, 2))
    total_liabilities = Column(Numeric(20, 2))
    total_equity = Column(Numeric(20, 2))
    goodwill = Column(Numeric(20, 2))

    # 现金流量表核心字段
    operating_cash_flow = Column(Numeric(20, 2))
    investing_cash_flow = Column(Numeric(20, 2))
    financing_cash_flow = Column(Numeric(20, 2))
    free_cash_flow = Column(Numeric(20, 2))

    # 衍生指标（计算字段）
    roe = Column(Numeric(8, 4))
    roa = Column(Numeric(8, 4))
    gross_margin = Column(Numeric(8, 4))
    net_margin = Column(Numeric(8, 4))
    debt_ratio = Column(Numeric(8, 4))

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    stock = relationship("Stock", back_populates="financials")

    __table_args__ = (
        UniqueConstraint("stock_code", "report_type", "report_date", name="uq_financials_stock_type_date"),
    )


# ===== Pydantic Schema =====

class FinancialResponse(BaseModel):
    id: int
    stock_code: str
    report_type: str
    report_date: date
    total_revenue: Optional[float] = None
    operating_revenue: Optional[float] = None
    operating_cost: Optional[float] = None
    gross_profit: Optional[float] = None
    net_profit: Optional[float] = None
    net_profit_deducted: Optional[float] = None
    total_assets: Optional[float] = None
    total_liabilities: Optional[float] = None
    total_equity: Optional[float] = None
    goodwill: Optional[float] = None
    operating_cash_flow: Optional[float] = None
    investing_cash_flow: Optional[float] = None
    financing_cash_flow: Optional[float] = None
    free_cash_flow: Optional[float] = None
    roe: Optional[float] = None
    roa: Optional[float] = None
    gross_margin: Optional[float] = None
    net_margin: Optional[float] = None
    debt_ratio: Optional[float] = None

    class Config:
        from_attributes = True
