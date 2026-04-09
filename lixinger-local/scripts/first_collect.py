"""
首次全量数据采集脚本

用法：
    cd lixinger-local
    # 采集全量数据（耗时较长）
    python scripts/first_collect.py

    # 只采集指定股票（测试用）
    python scripts/first_collect.py --codes 000001 600519 300750

    # 只采集核心表数据
    python scripts/first_collect.py --core-only --codes 000001 600519
"""
import sys
import os
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from database import init_db, SessionLocal
from collectors.scheduler import DataCollector
from collectors.core_collector import CoreCollector, _infer_ts_code
from utils.logger import setup_logging

setup_logging()


def main():
    parser = argparse.ArgumentParser(description="首次全量数据采集")
    parser.add_argument("--codes", nargs="*", help="指定股票代码（不填则采集全市场）")
    parser.add_argument(
        "--core-only",
        action="store_true",
        help="仅采集核心表（stock_basic, daily_market_valuation, quarterly_finance）",
    )
    args = parser.parse_args()

    print("初始化数据库...")
    init_db()

    db = SessionLocal()
    try:
        if args.core_only:
            # 仅采集核心表
            core = CoreCollector(db)
            print("采集股票基础信息...")
            core.collect_stock_basic()

            if args.codes:
                ts_codes = [_infer_ts_code(c) for c in args.codes]
            else:
                from models.core import StockBasic
                ts_codes = [
                    r[0]
                    for r in db.query(StockBasic.ts_code)
                    .filter(StockBasic.is_delist.is_(False))
                    .all()
                ]

            total = len(ts_codes)
            print(f"开始采集 {total} 只股票的核心数据...")
            for i, ts_code in enumerate(ts_codes):
                if i % 20 == 0:
                    print(f"进度: {i}/{total}，当前: {ts_code}")
                core.collect_daily_market_valuation(ts_code, force_full=True)
                core.collect_quarterly_finance(ts_code)
            print("核心表采集完成！")
        else:
            # 全量采集（旧表 + 核心表）
            collector = DataCollector(db)
            print(
                f"开始全量采集"
                f"{'（指定股票: ' + ', '.join(args.codes) + '）' if args.codes else '（全市场）'}"
                f"..."
            )
            collector.run_full_refresh(stock_codes=args.codes)
            print("采集完成！")
    finally:
        db.close()


if __name__ == "__main__":
    main()
