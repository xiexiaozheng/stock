"""
数据采集器基类

提供统一的重试、限流、fallback、upsert 等能力。
所有具体采集器都应继承此基类。
"""
import logging
import time
import random
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from utils.logger import get_logger
from utils.retry import retry
from utils.rate_limiter import akshare_limiter

logger = get_logger(__name__)


class BaseCollector(ABC):
    """采集器抽象基类"""

    def __init__(self, db: Session):
        self.db = db

    def _rate_limit(self, min_sec: float = 0.5, max_sec: float = 1.0):
        """随机延迟限流"""
        time.sleep(random.uniform(min_sec, max_sec))

    def _upsert(self, model_class, rows: List[Dict], conflict_columns: List[str]):
        """
        SQLite upsert：存在则更新，不存在则插入。

        :param model_class: SQLAlchemy 模型类
        :param rows: 待写入的字典列表
        :param conflict_columns: 用于判断冲突的列名列表
        """
        if not rows:
            return 0

        try:
            stmt = sqlite_insert(model_class.__table__)
            update_cols = {
                col.name: col
                for col in stmt.excluded
                if col.name not in conflict_columns and col.name not in ("id", "created_at")
            }
            stmt = stmt.on_conflict_do_update(
                index_elements=conflict_columns,
                set_=update_cols,
            )
            self.db.execute(stmt, rows)
            self.db.commit()
            logger.debug(f"upsert {len(rows)} 条数据到 {model_class.__tablename__}")
            return len(rows)
        except Exception as e:
            self.db.rollback()
            logger.error(f"upsert 失败 [{model_class.__tablename__}]: {e}")
            raise
