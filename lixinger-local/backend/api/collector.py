"""数据采集触发 API"""
import logging
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from collectors.scheduler import run_task_async, get_task_status

router = APIRouter(prefix="/api/collect", tags=["collector"])
logger = logging.getLogger(__name__)


class CollectRequest(BaseModel):
    scope: str = "incremental"  # incremental / full_refresh
    stock_codes: Optional[List[str]] = None  # 指定股票，为空则处理全部


@router.post("/trigger")
def trigger_collection(request: CollectRequest):
    """手动触发数据采集"""
    if request.scope not in ("incremental", "full_refresh"):
        raise HTTPException(status_code=400, detail="scope 必须是 incremental 或 full_refresh")

    success, message = run_task_async(
        task_type=request.scope,
        stock_codes=request.stock_codes,
    )
    if not success:
        raise HTTPException(status_code=409, detail=message)

    return {"message": message, "scope": request.scope}


@router.get("/status")
def get_collection_status():
    """获取采集任务状态"""
    return get_task_status()
