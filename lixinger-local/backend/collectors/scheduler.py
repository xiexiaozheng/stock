"""
数据采集调度器

统一管理全量刷新和增量更新的调度逻辑。
支持手动触发和定时调度（APScheduler）。

DataFetcherManager 生命周期由 DataCollector 管理：
  - 在 DataCollector 初始化时创建
  - 在采集任务结束时关闭
"""
import logging
import threading
from datetime import datetime, timedelta
from typing import Optional, List
from sqlalchemy.orm import Session

from database import SessionLocal
from collectors.akshare_collector import AkshareCollector
from collectors.core_collector import CoreCollector
from collectors.chrome_collector import ChromeCollector
from models.stock import Stock
from models.core import StockBasic
from utils.logger import get_logger
from config import (
    SCHEDULE_INCREMENTAL_TIME,
    HISTORY_YEARS_QUOTES,
)

# 多数据源框架
from data_provider.base import DataFetcherManager

logger = get_logger(__name__)


# 任务状态追踪（内存级，重启后重置）
_task_status = {
    "is_running": False,
    "last_run": None,
    "last_run_type": None,
    "last_error": None,
    "progress": "",
    "started_at": None,
}
_task_lock = threading.Lock()


def get_task_status() -> dict:
    return dict(_task_status)


class DataCollector:
    """统一数据采集调度器（多数据源版）"""

    def __init__(self, db: Session):
        self.db = db
        # 创建共享的 DataFetcherManager，注入到 CoreCollector
        self._manager = DataFetcherManager()
        self.akshare = AkshareCollector(db, manager=self._manager)
        self.chrome = ChromeCollector()
        self.core = CoreCollector(db, manager=self._manager)
        logger.info(
            f"DataCollector 初始化完成, "
            f"已注册 {len(self._manager.get_fetchers())} 个数据源"
        )

    def close(self):
        """释放资源"""
        try:
            self.akshare.close()
        except Exception as e:
            logger.warning(f"AkshareCollector close 异常: {e}")
        if self._manager:
            self._manager.close()
            self._manager = None

    # ======================== 增量更新 ========================

    def run_incremental_update(self):
        """
        增量更新流程（每日运行）：
        1. 更新股票列表（旧表 + 新核心表）
        2. 更新最新交易日行情
        3. 更新最新估值数据
        4. 检查并更新财报数据
        5. 更新分红数据
        6. 更新核心表（日度量价估值 + 季度财务）
        """
        logger.info("=== 开始增量更新 ===")
        _update_status("incremental", "更新股票列表...")

        self.akshare.collect_stock_list()
        self.core.collect_stock_basic()

        # 只更新数据库中已有的股票（旧表）
        codes = [r[0] for r in self.db.query(Stock.stock_code).filter(Stock.is_active == True).all()]
        total = len(codes)
        logger.info(f"增量更新 {total} 只股票的行情和估值数据")

        for i, code in enumerate(codes):
            if i % 50 == 0:
                _update_status("incremental", f"进度: {i}/{total}")
                logger.info(f"增量更新进度: {i}/{total}")

            # 行情（只拉最近N天缺口）
            today = datetime.today().strftime("%Y%m%d")
            self.akshare.collect_daily_quotes(code, end_date=today)

            # 估值（全量替换，akshare 返回完整历史）
            self.akshare.collect_valuations(code)

        # 财报（每季度披露后更新，检测最近90天）
        cutoff = datetime.today() - timedelta(days=90)
        for code in codes:
            self.akshare.collect_financials(code)

        # ---- 核心表增量更新 ----
        _update_status("incremental", "更新核心表...")
        core_codes = [r[0] for r in self.db.query(StockBasic.ts_code).filter(StockBasic.is_delist.is_(False)).all()]
        core_total = len(core_codes)
        for i, ts_code in enumerate(core_codes):
            if i % 50 == 0:
                _update_status("incremental", f"核心表进度: {i}/{core_total}")
            self.core.collect_daily_market_valuation(ts_code)

        # 最新估值快照（全市场一次性拉取）
        _update_status("incremental", "更新最新估值快照...")
        self.core.collect_latest_valuation_snapshot()

        logger.info("=== 增量更新完成 ===")

    # ======================== 全量刷新 ========================

    def run_full_refresh(self, stock_codes: Optional[List[str]] = None):
        """
        全量刷新（首次运行或定期全量）：
        1. 拉取全市场股票列表（旧表 + 新核心表）
        2. 拉取所有（或指定）股票近N年日线数据
        3. 拉取财务数据
        4. 拉取估值历史
        5. 拉取分红数据
        6. 全量填充核心表（日度量价估值 + 季度财务）
        """
        logger.info("=== 开始全量刷新 ===")
        _update_status("full_refresh", "采集股票列表...")

        self.akshare.collect_stock_list()
        self.core.collect_stock_basic()

        if stock_codes is None:
            codes = [r[0] for r in self.db.query(Stock.stock_code).filter(Stock.is_active == True).all()]
        else:
            codes = stock_codes

        total = len(codes)
        logger.info(f"全量刷新 {total} 只股票")

        for i, code in enumerate(codes):
            if i % 20 == 0:
                _update_status("full_refresh", f"进度: {i}/{total}，当前: {code}")
                logger.info(f"全量刷新进度: {i}/{total}，股票: {code}")

            start = (datetime.today() - timedelta(days=365 * HISTORY_YEARS_QUOTES)).strftime("%Y%m%d")
            self.akshare.collect_daily_quotes(code, start_date=start)
            self.akshare.collect_financials(code)
            self.akshare.collect_valuations(code)
            self.akshare.collect_dividends(code)

        # 行业板块
        _update_status("full_refresh", "采集行业板块数据...")
        self.akshare.collect_industries()

        # ---- 核心表全量刷新 ----
        _update_status("full_refresh", "全量填充核心表...")
        core_codes = [r[0] for r in self.db.query(StockBasic.ts_code).filter(StockBasic.is_delist.is_(False)).all()]
        core_total = len(core_codes)

        for i, ts_code in enumerate(core_codes):
            if i % 20 == 0:
                _update_status("full_refresh", f"核心表进度: {i}/{core_total}，当前: {ts_code}")
                logger.info(f"核心表全量刷新进度: {i}/{core_total}，股票: {ts_code}")

            self.core.collect_daily_market_valuation(ts_code, force_full=True)
            self.core.collect_quarterly_finance(ts_code)

        # 最新估值快照（全市场一次性拉取）
        _update_status("full_refresh", "采集最新估值快照...")
        self.core.collect_latest_valuation_snapshot()

        logger.info("=== 全量刷新完成 ===")


def _update_status(run_type: str, progress: str):
    _task_status["last_run_type"] = run_type
    _task_status["progress"] = progress


def run_task_async(task_type: str = "incremental", stock_codes: Optional[List[str]] = None):
    """在后台线程中异步执行采集任务"""
    with _task_lock:
        if _task_status["is_running"]:
            return False, "任务已在运行中"
        _task_status["is_running"] = True
        _task_status["started_at"] = datetime.now().isoformat()
        _task_status["last_error"] = None

    def _run():
        db = SessionLocal()
        collector = None
        try:
            collector = DataCollector(db)
            if task_type == "full_refresh":
                collector.run_full_refresh(stock_codes)
            else:
                collector.run_incremental_update()
            _task_status["last_run"] = datetime.now().isoformat()
        except Exception as e:
            logger.error(f"采集任务异常: {e}", exc_info=True)
            _task_status["last_error"] = str(e)
        finally:
            _task_status["is_running"] = False
            _task_status["progress"] = "已完成"
            try:
                if collector:
                    collector.close()
            except Exception as e:
                logger.warning(f"DataCollector close 异常: {e}")
            db.close()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return True, "任务已启动"


def setup_scheduler():
    """配置 APScheduler 定时任务"""
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger

        scheduler = BackgroundScheduler(timezone="Asia/Shanghai")

        # 每个交易日 15:35 增量更新
        hour, minute = SCHEDULE_INCREMENTAL_TIME.split(":")
        scheduler.add_job(
            lambda: run_task_async("incremental"),
            CronTrigger(day_of_week="mon-fri", hour=int(hour), minute=int(minute)),
            id="incremental_update",
            replace_existing=True,
        )

        # 每周日凌晨 2:00 全量刷新
        scheduler.add_job(
            lambda: run_task_async("full_refresh"),
            CronTrigger(day_of_week="sun", hour=2, minute=0),
            id="full_refresh",
            replace_existing=True,
        )

        scheduler.start()
        logger.info("调度器已启动")
        return scheduler
    except ImportError:
        logger.warning("APScheduler 未安装，定时任务不可用。运行 pip install apscheduler 启用")
        return None
