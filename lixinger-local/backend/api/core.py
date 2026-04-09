"""
核心数据 API 路由

提供三张核心表和指标计算框架的 API 接口。
"""
import logging
from typing import Optional
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from models.core import (
    StockBasic,
    DailyMarketValuation,
    QuarterlyFinance,
    StockBasicResponse,
    StockBasicListResponse,
    DailyMarketValuationResponse,
    QuarterlyFinanceResponse,
)
from analyzers.data_reader import DataReader
from analyzers.indicator_framework import IndicatorRegistry

# 确保内置指标被注册
import analyzers.builtin_indicators  # noqa: F401

router = APIRouter(prefix="/api/core", tags=["core"])
logger = logging.getLogger(__name__)


# ======================== 股票基础信息 ========================

@router.get("/stocks", response_model=StockBasicListResponse)
def list_stock_basic(
    q: Optional[str] = Query(None, description="搜索关键词（代码或名称）"),
    industry: Optional[str] = Query(None, description="行业筛选"),
    include_delisted: bool = Query(False, description="是否包含已退市"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """获取股票基础信息列表"""
    query = db.query(StockBasic)

    if not include_delisted:
        query = query.filter(StockBasic.is_delist.is_(False))
    if q:
        query = query.filter(
            (StockBasic.ts_code.contains(q)) | (StockBasic.name.contains(q))
        )
    if industry:
        query = query.filter(StockBasic.industry.contains(industry))

    total = query.count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()

    return StockBasicListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[StockBasicResponse.model_validate(s) for s in items],
    )


@router.get("/stocks/{ts_code}", response_model=StockBasicResponse)
def get_stock_basic(ts_code: str, db: Session = Depends(get_db)):
    """获取单只股票基础信息"""
    stock = db.query(StockBasic).filter(StockBasic.ts_code == ts_code).first()
    if not stock:
        raise HTTPException(status_code=404, detail=f"股票 {ts_code} 不存在")
    return StockBasicResponse.model_validate(stock)


# ======================== 日度量价与估值 ========================

@router.get(
    "/stocks/{ts_code}/daily",
    response_model=list[DailyMarketValuationResponse],
)
def get_daily_market_valuation(
    ts_code: str,
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    limit: int = Query(2000, ge=1, le=5000),
    db: Session = Depends(get_db),
):
    """获取日度量价与估值数据"""
    query = db.query(DailyMarketValuation).filter(
        DailyMarketValuation.ts_code == ts_code
    )
    if start_date:
        query = query.filter(DailyMarketValuation.trade_date >= start_date)
    if end_date:
        query = query.filter(DailyMarketValuation.trade_date <= end_date)
    query = query.order_by(DailyMarketValuation.trade_date.asc())

    rows = query.limit(limit).all()
    return [DailyMarketValuationResponse.model_validate(r) for r in rows]


# ======================== 季度财务 ========================

@router.get(
    "/stocks/{ts_code}/finance",
    response_model=list[QuarterlyFinanceResponse],
)
def get_quarterly_finance(
    ts_code: str,
    annual_only: bool = Query(False, description="是否仅返回年报"),
    years: int = Query(5, ge=1, le=20),
    db: Session = Depends(get_db),
):
    """获取季度财务核心数据"""
    query = db.query(QuarterlyFinance).filter(
        QuarterlyFinance.ts_code == ts_code
    )
    if annual_only:
        from sqlalchemy import extract
        query = query.filter(extract("month", QuarterlyFinance.end_date) == 12)
    query = query.order_by(QuarterlyFinance.end_date.desc())
    rows = query.limit(years * 4).all()
    return [QuarterlyFinanceResponse.model_validate(r) for r in rows]


# ======================== 指标计算 ========================

@router.get("/indicators")
def list_indicators():
    """列出所有已注册的指标"""
    return IndicatorRegistry.list_indicators()


@router.get("/stocks/{ts_code}/indicator/{indicator_name}")
def compute_indicator(
    ts_code: str,
    indicator_name: str,
    years: int = Query(5, ge=1, le=20),
    db: Session = Depends(get_db),
):
    """
    计算指定股票的指定指标。

    示例：
    - GET /api/core/stocks/000001.SZ/indicator/pe_percentile?years=5
    - GET /api/core/stocks/600519.SH/indicator/pb_percentile?years=3
    """
    try:
        registry = IndicatorRegistry(db)
        result = registry.compute(indicator_name, ts_code=ts_code, years=years)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"指标计算失败 [{indicator_name}/{ts_code}]: {e}")
        raise HTTPException(status_code=500, detail=f"指标计算失败: {e}")


# ======================== 综合仪表盘 ========================

@router.get("/stocks/{ts_code}/dashboard")
def get_core_dashboard(ts_code: str, db: Session = Depends(get_db)):
    """
    核心表综合仪表盘（聚合接口）

    返回：基础信息 + 最新估值 + 最新财务 + PE/PB 百分位
    """
    stock = db.query(StockBasic).filter(StockBasic.ts_code == ts_code).first()
    if not stock:
        raise HTTPException(status_code=404, detail=f"股票 {ts_code} 不存在")

    # 最新估值
    latest_val = (
        db.query(DailyMarketValuation)
        .filter(DailyMarketValuation.ts_code == ts_code)
        .order_by(DailyMarketValuation.trade_date.desc())
        .first()
    )

    # 最新年报财务
    from sqlalchemy import extract
    latest_fin = (
        db.query(QuarterlyFinance)
        .filter(
            QuarterlyFinance.ts_code == ts_code,
            extract("month", QuarterlyFinance.end_date) == 12,
        )
        .order_by(QuarterlyFinance.end_date.desc())
        .first()
    )

    # 指标计算
    registry = IndicatorRegistry(db)
    pe_result = {}
    pb_result = {}
    try:
        pe_result = registry.compute("pe_percentile", ts_code=ts_code, years=5)
    except Exception as e:
        logger.warning(f"PE 百分位计算失败 [{ts_code}]: {e}")
    try:
        pb_result = registry.compute("pb_percentile", ts_code=ts_code, years=5)
    except Exception as e:
        logger.warning(f"PB 百分位计算失败 [{ts_code}]: {e}")

    return {
        "stock": StockBasicResponse.model_validate(stock),
        "valuation": (
            DailyMarketValuationResponse.model_validate(latest_val)
            if latest_val
            else None
        ),
        "finance": (
            QuarterlyFinanceResponse.model_validate(latest_fin)
            if latest_fin
            else None
        ),
        "indicators": {
            "pe_percentile": pe_result,
            "pb_percentile": pb_result,
        },
    }
