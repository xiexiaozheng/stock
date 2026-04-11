"""筛选器与行业板块数据模型"""
from datetime import datetime
from typing import Optional
from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, UniqueConstraint
from pydantic import BaseModel

from database import Base


class Screener(Base):
    __tablename__ = "screeners"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    conditions_json = Column(Text, nullable=False)  # JSON 格式的筛选条件
    created_at = Column(DateTime, default=datetime.utcnow)
    last_run_at = Column(DateTime, nullable=True)


class Industry(Base):
    __tablename__ = "industries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class IndustryMember(Base):
    __tablename__ = "industry_members"

    id = Column(Integer, primary_key=True, autoincrement=True)
    industry_name = Column(String(100), ForeignKey("industries.name"), nullable=False)
    stock_code = Column(String(10), nullable=False)
    stock_name = Column(String(50), nullable=True)

    __table_args__ = (
        UniqueConstraint("industry_name", "stock_code", name="uq_industry_member"),
    )


# ===== Pydantic Schema =====

class ScreenerCreate(BaseModel):
    name: str
    conditions_json: str


class ScreenerResponse(BaseModel):
    id: int
    name: str
    conditions_json: str
    created_at: datetime
    last_run_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ScreenerRunRequest(BaseModel):
    conditions: dict
    save_as: Optional[str] = None


class ScreenerRunResponse(BaseModel):
    total: int
    results: list[dict]
