"""股票相关数据模型"""
from datetime import datetime, date
from typing import Optional
from sqlalchemy import Column, Integer, String, Boolean, Date, DateTime, BigInteger, Numeric, Text, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from pydantic import BaseModel

from database import Base


# ===== SQLAlchemy ORM 模型 =====

class Stock(Base):
    __tablename__ = "stocks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    stock_code = Column(String(10), nullable=False, unique=True)
    stock_name = Column(String(50), nullable=False)
    exchange = Column(String(5), nullable=False)  # SH / SZ / BJ
    listing_date = Column(Date, nullable=True)
    industry = Column(String(50), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    daily_quotes = relationship("DailyQuote", back_populates="stock", lazy="dynamic")
    financials = relationship("Financial", back_populates="stock", lazy="dynamic")
    valuations = relationship("Valuation", back_populates="stock", lazy="dynamic")
    dividends = relationship("Dividend", back_populates="stock", lazy="dynamic")


class DailyQuote(Base):
    __tablename__ = "daily_quotes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    stock_code = Column(String(10), ForeignKey("stocks.stock_code"), nullable=False)
    trade_date = Column(Date, nullable=False)
    open = Column(Numeric(10, 2))
    high = Column(Numeric(10, 2))
    low = Column(Numeric(10, 2))
    close = Column(Numeric(10, 2))
    volume = Column(BigInteger)
    amount = Column(Numeric(20, 2))
    turnover_rate = Column(Numeric(8, 4))
    amplitude = Column(Numeric(8, 4))

    stock = relationship("Stock", back_populates="daily_quotes")

    __table_args__ = (
        UniqueConstraint("stock_code", "trade_date", name="uq_daily_quotes_stock_date"),
        {"sqlite_autoincrement": False},
    )


class Watchlist(Base):
    __tablename__ = "watchlist"

    id = Column(Integer, primary_key=True, autoincrement=True)
    stock_code = Column(String(10), ForeignKey("stocks.stock_code"), nullable=False, unique=True)
    added_at = Column(DateTime, default=datetime.utcnow)
    notes = Column(Text, nullable=True)
    sort_order = Column(Integer, default=0)


# ===== Pydantic Schema 模型 =====

class StockBase(BaseModel):
    stock_code: str
    stock_name: str
    exchange: str
    listing_date: Optional[date] = None
    industry: Optional[str] = None
    is_active: bool = True


class StockCreate(StockBase):
    pass


class StockResponse(StockBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class StockListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[StockResponse]


class DailyQuoteResponse(BaseModel):
    stock_code: str
    trade_date: date
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    volume: Optional[int] = None
    amount: Optional[float] = None
    turnover_rate: Optional[float] = None
    amplitude: Optional[float] = None

    class Config:
        from_attributes = True


class WatchlistItemCreate(BaseModel):
    stock_code: str
    notes: Optional[str] = None
    sort_order: int = 0


class WatchlistItemResponse(BaseModel):
    id: int
    stock_code: str
    stock_name: Optional[str] = None
    added_at: datetime
    notes: Optional[str] = None
    sort_order: int

    class Config:
        from_attributes = True
