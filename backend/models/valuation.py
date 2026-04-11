"""估值与分红数据模型"""
from datetime import datetime, date
from typing import Optional
from sqlalchemy import Column, Integer, String, Date, DateTime, Numeric, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from pydantic import BaseModel

from database import Base


class Valuation(Base):
    __tablename__ = "valuations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    stock_code = Column(String(10), ForeignKey("stocks.stock_code"), nullable=False)
    trade_date = Column(Date, nullable=False)
    pe_ttm = Column(Numeric(12, 2))
    pb = Column(Numeric(12, 2))
    ps_ttm = Column(Numeric(12, 2))
    total_market_value = Column(Numeric(20, 2))
    circulating_market_value = Column(Numeric(20, 2))
    dividend_yield = Column(Numeric(8, 4))

    stock = relationship("Stock", back_populates="valuations")

    __table_args__ = (
        UniqueConstraint("stock_code", "trade_date", name="uq_valuations_stock_date"),
    )


class Dividend(Base):
    __tablename__ = "dividends"

    id = Column(Integer, primary_key=True, autoincrement=True)
    stock_code = Column(String(10), ForeignKey("stocks.stock_code"), nullable=False)
    ex_dividend_date = Column(Date, nullable=True)
    bonus_ratio = Column(Numeric(8, 2))       # 每10股送X股
    cash_dividend = Column(Numeric(10, 4))    # 每股派息（元）
    capital_increase = Column(Numeric(8, 2))  # 每10股转增X股

    stock = relationship("Stock", back_populates="dividends")

    __table_args__ = (
        UniqueConstraint("stock_code", "ex_dividend_date", name="uq_dividends_stock_date"),
    )


# ===== Pydantic Schema =====

class ValuationResponse(BaseModel):
    id: int
    stock_code: str
    trade_date: date
    pe_ttm: Optional[float] = None
    pb: Optional[float] = None
    ps_ttm: Optional[float] = None
    total_market_value: Optional[float] = None
    circulating_market_value: Optional[float] = None
    dividend_yield: Optional[float] = None

    class Config:
        from_attributes = True


class DividendResponse(BaseModel):
    id: int
    stock_code: str
    ex_dividend_date: Optional[date] = None
    bonus_ratio: Optional[float] = None
    cash_dividend: Optional[float] = None
    capital_increase: Optional[float] = None

    class Config:
        from_attributes = True
