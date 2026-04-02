"""股票相关 API 路由"""
import logging
from typing import Optional
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text

from database import get_db
from models.stock import Stock, DailyQuote, StockResponse, StockListResponse, DailyQuoteResponse
from models.financial import Financial, FinancialResponse
from models.valuation import Valuation, Dividend, ValuationResponse, DividendResponse
from analyzers.metrics import calc_percentile, calc_quantile_levels, calc_growth_rate

router = APIRouter(prefix="/api/stocks", tags=["stocks"])
logger = logging.getLogger(__name__)


@router.get("", response_model=StockListResponse)
def list_stocks(
    q: Optional[str] = Query(None, description="搜索关键词（代码或名称）"),
    exchange: Optional[str] = Query(None, description="交易所筛选 SH/SZ/BJ"),
    industry: Optional[str] = Query(None, description="行业筛选"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """获取股票列表，支持搜索和分页"""
    query = db.query(Stock).filter(Stock.is_active == True)

    if q:
        query = query.filter(
            (Stock.stock_code.contains(q)) | (Stock.stock_name.contains(q))
        )
    if exchange:
        query = query.filter(Stock.exchange == exchange.upper())
    if industry:
        query = query.filter(Stock.industry.contains(industry))

    total = query.count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()

    return StockListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[StockResponse.model_validate(s) for s in items],
    )


@router.get("/{code}", response_model=StockResponse)
def get_stock(code: str, db: Session = Depends(get_db)):
    """获取单只股票基本信息"""
    stock = db.query(Stock).filter(Stock.stock_code == code).first()
    if not stock:
        raise HTTPException(status_code=404, detail=f"股票 {code} 不存在")
    return StockResponse.model_validate(stock)


@router.get("/{code}/quotes", response_model=list[DailyQuoteResponse])
def get_quotes(
    code: str,
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    period: str = Query("daily", description="数据周期 daily/weekly/monthly"),
    db: Session = Depends(get_db),
):
    """获取行情数据"""
    query = db.query(DailyQuote).filter(DailyQuote.stock_code == code)
    if start_date:
        query = query.filter(DailyQuote.trade_date >= start_date)
    if end_date:
        query = query.filter(DailyQuote.trade_date <= end_date)
    query = query.order_by(DailyQuote.trade_date.asc())

    rows = query.limit(2000).all()
    return [DailyQuoteResponse.model_validate(r) for r in rows]


@router.get("/{code}/financials", response_model=list[FinancialResponse])
def get_financials(
    code: str,
    report_type: Optional[str] = Query(None, description="报告类型 annual/Q1/Q2/Q3"),
    years: int = Query(5, ge=1, le=10),
    db: Session = Depends(get_db),
):
    """获取财务报表数据"""
    query = db.query(Financial).filter(Financial.stock_code == code)
    if report_type:
        query = query.filter(Financial.report_type == report_type)
    rows = query.order_by(Financial.report_date.desc()).limit(years * 4).all()
    return [FinancialResponse.model_validate(r) for r in rows]


@router.get("/{code}/valuations", response_model=list[ValuationResponse])
def get_valuations(
    code: str,
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
):
    """获取估值历史数据（含历史分位）"""
    query = db.query(Valuation).filter(Valuation.stock_code == code)
    if start_date:
        query = query.filter(Valuation.trade_date >= start_date)
    if end_date:
        query = query.filter(Valuation.trade_date <= end_date)
    rows = query.order_by(Valuation.trade_date.asc()).limit(3000).all()
    return [ValuationResponse.model_validate(r) for r in rows]


@router.get("/{code}/dividends", response_model=list[DividendResponse])
def get_dividends(code: str, db: Session = Depends(get_db)):
    """获取分红历史"""
    rows = (
        db.query(Dividend)
        .filter(Dividend.stock_code == code)
        .order_by(Dividend.ex_dividend_date.desc())
        .all()
    )
    return [DividendResponse.model_validate(r) for r in rows]


@router.get("/{code}/dashboard")
def get_dashboard(code: str, db: Session = Depends(get_db)):
    """获取股票综合仪表盘数据（聚合接口）"""
    stock = db.query(Stock).filter(Stock.stock_code == code).first()
    if not stock:
        raise HTTPException(status_code=404, detail=f"股票 {code} 不存在")

    # 最新估值
    latest_val = (
        db.query(Valuation)
        .filter(Valuation.stock_code == code)
        .order_by(Valuation.trade_date.desc())
        .first()
    )

    # 最新年报财务
    latest_fin = (
        db.query(Financial)
        .filter(Financial.stock_code == code, Financial.report_type == "annual")
        .order_by(Financial.report_date.desc())
        .first()
    )

    # 近5年PE历史（计算分位）
    pe_history = [
        float(r.pe_ttm)
        for r in db.query(Valuation.pe_ttm)
        .filter(Valuation.stock_code == code, Valuation.pe_ttm.isnot(None))
        .all()
    ]
    pe_quantiles = calc_quantile_levels(pe_history) if pe_history else {}
    current_pe = float(latest_val.pe_ttm) if latest_val and latest_val.pe_ttm else None
    pe_percentile = calc_percentile(current_pe, pe_history) if current_pe else None

    # 近3年营收增长
    annual_fins = (
        db.query(Financial)
        .filter(Financial.stock_code == code, Financial.report_type == "annual")
        .order_by(Financial.report_date.desc())
        .limit(5)
        .all()
    )
    revenues = [float(f.operating_revenue) for f in reversed(annual_fins) if f.operating_revenue]
    profits = [float(f.net_profit) for f in reversed(annual_fins) if f.net_profit]
    revenue_growth = calc_growth_rate(revenues)
    profit_growth = calc_growth_rate(profits)

    return {
        "stock": StockResponse.model_validate(stock),
        "valuation": ValuationResponse.model_validate(latest_val) if latest_val else None,
        "financial": FinancialResponse.model_validate(latest_fin) if latest_fin else None,
        "metrics": {
            "pe_percentile": pe_percentile,
            "pe_quantiles": pe_quantiles,
            "revenue_growth_3y": revenue_growth,
            "profit_growth_3y": profit_growth,
        },
    }
