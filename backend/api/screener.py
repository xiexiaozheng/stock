"""筛选器 API 路由"""
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models.screener import Screener, ScreenerCreate, ScreenerResponse, ScreenerRunRequest, ScreenerRunResponse
from analyzers.screener_engine import ScreenerEngine, PRESET_SCREENERS

router = APIRouter(prefix="/api/screener", tags=["screener"])
logger = logging.getLogger(__name__)


@router.post("/run", response_model=ScreenerRunResponse)
def run_screener(request: ScreenerRunRequest, db: Session = Depends(get_db)):
    """运行筛选器"""
    engine = ScreenerEngine(db)
    try:
        results = engine.run(request.conditions)
    except Exception as e:
        logger.error(f"筛选器执行失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"筛选器执行失败: {str(e)}")

    # 可选：保存筛选条件
    if request.save_as:
        screener = Screener(
            name=request.save_as,
            conditions_json=json.dumps(request.conditions, ensure_ascii=False),
        )
        db.add(screener)
        db.commit()

    return ScreenerRunResponse(total=len(results), results=results)


@router.get("/presets")
def get_presets():
    """获取预设筛选模板"""
    return PRESET_SCREENERS


@router.get("/saved", response_model=list[ScreenerResponse])
def list_saved_screeners(db: Session = Depends(get_db)):
    """获取已保存的筛选器列表"""
    return db.query(Screener).order_by(Screener.created_at.desc()).all()


@router.delete("/saved/{screener_id}")
def delete_screener(screener_id: int, db: Session = Depends(get_db)):
    """删除已保存的筛选器"""
    screener = db.query(Screener).filter(Screener.id == screener_id).first()
    if not screener:
        raise HTTPException(status_code=404, detail="筛选器不存在")
    db.delete(screener)
    db.commit()
    return {"message": "已删除"}
