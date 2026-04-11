"""自选股 API 路由"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text

from database import get_db
from models.stock import Watchlist, WatchlistItemCreate, WatchlistItemResponse

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])
logger = logging.getLogger(__name__)


@router.get("", response_model=list[WatchlistItemResponse])
def get_watchlist(db: Session = Depends(get_db)):
    """获取自选股列表（含最新行情和估值）"""
    sql = text("""
        SELECT
            w.id,
            w.stock_code,
            s.stock_name,
            w.added_at,
            w.notes,
            w.sort_order,
            v.pe_ttm,
            v.pb,
            v.dividend_yield,
            v.total_market_value,
            q.close,
            q.turnover_rate,
            -- 涨跌幅（最近两日对比）
            CASE WHEN q_prev.close IS NOT NULL AND q_prev.close > 0
                 THEN ROUND((q.close - q_prev.close) / q_prev.close * 100, 2)
                 ELSE NULL
            END AS change_pct
        FROM watchlist w
        LEFT JOIN stocks s ON w.stock_code = s.stock_code
        LEFT JOIN valuations v ON w.stock_code = v.stock_code
            AND v.trade_date = (SELECT MAX(trade_date) FROM valuations WHERE stock_code = w.stock_code)
        LEFT JOIN daily_quotes q ON w.stock_code = q.stock_code
            AND q.trade_date = (SELECT MAX(trade_date) FROM daily_quotes WHERE stock_code = w.stock_code)
        LEFT JOIN daily_quotes q_prev ON w.stock_code = q_prev.stock_code
            AND q_prev.trade_date = (
                SELECT MAX(trade_date) FROM daily_quotes
                WHERE stock_code = w.stock_code
                  AND trade_date < (SELECT MAX(trade_date) FROM daily_quotes WHERE stock_code = w.stock_code)
            )
        ORDER BY w.sort_order ASC, w.added_at DESC
    """)

    rows = db.execute(sql).fetchall()
    result = []
    for row in rows:
        item = WatchlistItemResponse(
            id=row[0],
            stock_code=row[1],
            stock_name=row[2],
            added_at=row[3],
            notes=row[4],
            sort_order=row[5],
        )
        result.append(item)
    return result


@router.post("", response_model=WatchlistItemResponse, status_code=201)
def add_to_watchlist(item: WatchlistItemCreate, db: Session = Depends(get_db)):
    """添加自选股"""
    existing = db.query(Watchlist).filter(Watchlist.stock_code == item.stock_code).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"{item.stock_code} 已在自选股列表中")

    wl = Watchlist(
        stock_code=item.stock_code,
        notes=item.notes,
        sort_order=item.sort_order,
    )
    db.add(wl)
    db.commit()
    db.refresh(wl)

    stock = db.execute(
        text("SELECT stock_name FROM stocks WHERE stock_code = :code"),
        {"code": item.stock_code},
    ).fetchone()

    return WatchlistItemResponse(
        id=wl.id,
        stock_code=wl.stock_code,
        stock_name=stock[0] if stock else None,
        added_at=wl.added_at,
        notes=wl.notes,
        sort_order=wl.sort_order,
    )


@router.delete("/{code}")
def remove_from_watchlist(code: str, db: Session = Depends(get_db)):
    """删除自选股"""
    wl = db.query(Watchlist).filter(Watchlist.stock_code == code).first()
    if not wl:
        raise HTTPException(status_code=404, detail=f"{code} 不在自选股列表中")
    db.delete(wl)
    db.commit()
    return {"message": f"{code} 已从自选股移除"}


@router.put("/{code}/sort")
def update_sort_order(code: str, sort_order: int, db: Session = Depends(get_db)):
    """更新自选股排序"""
    wl = db.query(Watchlist).filter(Watchlist.stock_code == code).first()
    if not wl:
        raise HTTPException(status_code=404, detail=f"{code} 不在自选股列表中")
    wl.sort_order = sort_order
    db.commit()
    return {"message": "排序已更新"}
